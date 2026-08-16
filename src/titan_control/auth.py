"""Static bootstrap authentication for the self-hosted control-plane API."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from base64 import b64decode, urlsafe_b64encode
from dataclasses import dataclass
from typing import Mapping, Protocol

from titan_control.domain import Identity


class AuthenticationConfigurationError(ValueError):
    pass


class AuthenticationError(RuntimeError):
    pass


class Authenticator(Protocol):
    def authenticate(self, authorization_header: str | None) -> Identity: ...


@dataclass(frozen=True, slots=True)
class IdentityRecord:
    token_sha256: str
    identity: Identity


class TokenAuthenticator:
    def __init__(self, records: tuple[IdentityRecord, ...]) -> None:
        if not records:
            raise AuthenticationConfigurationError(
                "at least one authentication record is required"
            )
        self.records = records

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "TokenAuthenticator":
        source = os.environ if environ is None else environ
        records: list[IdentityRecord] = []

        admin_token = source.get("TITAN_ADMIN_TOKEN", "")
        if admin_token:
            if len(admin_token) < 24:
                raise AuthenticationConfigurationError(
                    "TITAN_ADMIN_TOKEN must contain at least 24 characters"
                )
            records.append(
                IdentityRecord(
                    token_sha256=_hash_token(admin_token),
                    identity=Identity("bootstrap-admin", ("admin",)),
                )
            )

        raw_identities = source.get("TITAN_IDENTITIES_JSON", "[]")
        try:
            identities = json.loads(raw_identities)
        except json.JSONDecodeError as error:
            raise AuthenticationConfigurationError(
                "TITAN_IDENTITIES_JSON must contain valid JSON"
            ) from error
        if not isinstance(identities, list):
            raise AuthenticationConfigurationError(
                "TITAN_IDENTITIES_JSON must contain an array"
            )

        for index, document in enumerate(identities):
            if not isinstance(document, dict):
                raise AuthenticationConfigurationError(
                    f"identity record {index} must be an object"
                )
            try:
                token_sha256 = str(document["token_sha256"])
                subject = str(document["subject"])
                roles = tuple(str(role) for role in document["roles"])
                project_ids = tuple(
                    str(project_id) for project_id in document.get("project_ids", [])
                )
            except (KeyError, TypeError) as error:
                raise AuthenticationConfigurationError(
                    f"identity record {index} is incomplete"
                ) from error
            if len(token_sha256) != 64 or any(
                character not in "0123456789abcdef" for character in token_sha256
            ):
                raise AuthenticationConfigurationError(
                    f"identity record {index} has an invalid SHA-256 token hash"
                )
            if not subject or not roles:
                raise AuthenticationConfigurationError(
                    f"identity record {index} requires subject and roles"
                )
            records.append(
                IdentityRecord(
                    token_sha256=token_sha256,
                    identity=Identity(subject, roles, project_ids),
                )
            )

        return cls(tuple(records))

    def authenticate(self, authorization_header: str | None) -> Identity:
        if not authorization_header:
            raise AuthenticationError("Authorization header is required")
        scheme, separator, token = authorization_header.partition(" ")
        if separator != " " or scheme.lower() != "bearer" or not token:
            raise AuthenticationError("Authorization must use the Bearer scheme")
        candidate_hash = _hash_token(token)
        for record in self.records:
            if hmac.compare_digest(candidate_hash, record.token_sha256):
                return record.identity
        raise AuthenticationError("Bearer token is invalid")


class JWTAuthenticator:
    """Strict HS256 JWT verifier for local identity labs and service automation."""

    def __init__(self, *, secret: str, issuer: str, audience: str) -> None:
        if len(secret.encode("utf-8")) < 32:
            raise AuthenticationConfigurationError(
                "TITAN_JWT_SECRET must contain at least 32 UTF-8 bytes"
            )
        if not issuer or not audience:
            raise AuthenticationConfigurationError("JWT issuer and audience are required")
        self.secret = secret.encode("utf-8")
        self.issuer = issuer
        self.audience = audience

    def authenticate(self, authorization_header: str | None) -> Identity:
        token = _bearer_token(authorization_header)
        parts = token.split(".")
        if len(parts) != 3:
            raise AuthenticationError("Bearer token is not a compact JWT")
        signing_input = f"{parts[0]}.{parts[1]}".encode("ascii")
        try:
            header = json.loads(_decode_segment(parts[0]))
            claims = json.loads(_decode_segment(parts[1]))
            signature = _decode_segment(parts[2])
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            raise AuthenticationError("JWT encoding is invalid") from error
        if not isinstance(header, dict) or header.get("alg") != "HS256" or header.get("typ") not in {None, "JWT"}:
            raise AuthenticationError("JWT algorithm or type is not permitted")
        if not isinstance(claims, dict):
            raise AuthenticationError("JWT claims must be an object")
        expected = hmac.new(self.secret, signing_input, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise AuthenticationError("JWT signature is invalid")
        now = int(time.time())
        try:
            expires_at = int(claims["exp"])
            not_before = int(claims.get("nbf", 0))
        except (KeyError, TypeError, ValueError) as error:
            raise AuthenticationError("JWT requires numeric exp and optional nbf") from error
        if expires_at <= now or not_before > now + 30:
            raise AuthenticationError("JWT is expired or not yet valid")
        if claims.get("iss") != self.issuer:
            raise AuthenticationError("JWT issuer is invalid")
        audiences = claims.get("aud")
        valid_audience = (
            audiences == self.audience
            if isinstance(audiences, str)
            else isinstance(audiences, list) and self.audience in audiences
        )
        if not valid_audience:
            raise AuthenticationError("JWT audience is invalid")
        subject = claims.get("sub")
        roles = claims.get("roles")
        projects = claims.get("project_ids", [])
        if (
            not isinstance(subject, str)
            or not subject
            or not isinstance(roles, list)
            or not roles
            or not all(isinstance(role, str) and role for role in roles)
            or not isinstance(projects, list)
            or not all(isinstance(project, str) for project in projects)
        ):
            raise AuthenticationError("JWT identity claims are incomplete")
        return Identity(subject, tuple(roles), tuple(projects))


class CompositeAuthenticator:
    def __init__(self, authenticators: tuple[Authenticator, ...]) -> None:
        if not authenticators:
            raise AuthenticationConfigurationError(
                "at least one authentication method must be configured"
            )
        self.authenticators = authenticators

    def authenticate(self, authorization_header: str | None) -> Identity:
        errors: list[str] = []
        for authenticator in self.authenticators:
            try:
                return authenticator.authenticate(authorization_header)
            except AuthenticationError as error:
                errors.append(str(error))
        raise AuthenticationError("Bearer token did not match any configured identity method")


def authenticator_from_environ(
    environ: Mapping[str, str] | None = None,
) -> Authenticator:
    source = os.environ if environ is None else environ
    authenticators: list[Authenticator] = []
    raw_identities = source.get("TITAN_IDENTITIES_JSON", "[]")
    if source.get("TITAN_ADMIN_TOKEN") or raw_identities.strip() != "[]":
        authenticators.append(TokenAuthenticator.from_environ(source))
    jwt_secret = source.get("TITAN_JWT_SECRET", "")
    if jwt_secret:
        authenticators.append(
            JWTAuthenticator(
                secret=jwt_secret,
                issuer=source.get("TITAN_JWT_ISSUER", "titan-local"),
                audience=source.get("TITAN_JWT_AUDIENCE", "titan"),
            )
        )
    return CompositeAuthenticator(tuple(authenticators))


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _bearer_token(authorization_header: str | None) -> str:
    if not authorization_header:
        raise AuthenticationError("Authorization header is required")
    scheme, separator, token = authorization_header.partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not token:
        raise AuthenticationError("Authorization must use the Bearer scheme")
    return token


def _decode_segment(value: str) -> bytes:
    if not value or "=" in value:
        raise ValueError("JWT segments must use unpadded Base64URL")
    padding = "=" * (-len(value) % 4)
    decoded = b64decode(value + padding, altchars=b"-_", validate=True)
    canonical = urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii")
    if not hmac.compare_digest(canonical, value):
        raise ValueError("JWT segment is not canonical Base64URL")
    return decoded
