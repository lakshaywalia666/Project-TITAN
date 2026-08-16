from __future__ import annotations

import hashlib
import hmac
import json
import time
import unittest
from base64 import urlsafe_b64encode

from titan_control.auth import AuthenticationError, JWTAuthenticator, authenticator_from_environ


def encode_segment(value: object) -> str:
    raw = json.dumps(value, separators=(",", ":")).encode("utf-8")
    return urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def token(secret: str, claims: dict[str, object]) -> str:
    header = encode_segment({"alg": "HS256", "typ": "JWT"})
    payload = encode_segment(claims)
    signature = hmac.new(secret.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
    return f"{header}.{payload}.{urlsafe_b64encode(signature).rstrip(b'=').decode()}"


class JWTAuthenticatorTests(unittest.TestCase):
    SECRET = "a-local-test-secret-that-is-long-enough"

    def claims(self) -> dict[str, object]:
        return {
            "iss": "titan-local",
            "aud": "titan",
            "sub": "workload:catalog",
            "roles": ["agent"],
            "project_ids": ["prj_a"],
            "exp": int(time.time()) + 300,
        }

    def test_signed_short_lived_identity_is_accepted(self) -> None:
        identity = JWTAuthenticator(
            secret=self.SECRET, issuer="titan-local", audience="titan"
        ).authenticate(f"Bearer {token(self.SECRET, self.claims())}")
        self.assertEqual("workload:catalog", identity.subject)
        self.assertEqual(("prj_a",), identity.project_ids)

    def test_tampered_and_expired_tokens_are_rejected(self) -> None:
        authenticator = JWTAuthenticator(
            secret=self.SECRET, issuer="titan-local", audience="titan"
        )
        valid = token(self.SECRET, self.claims())
        with self.assertRaises(AuthenticationError):
            authenticator.authenticate("Bearer " + valid[:-1] + ("A" if valid[-1] != "A" else "B"))
        expired = self.claims()
        expired["exp"] = int(time.time()) - 1
        with self.assertRaises(AuthenticationError):
            authenticator.authenticate(f"Bearer {token(self.SECRET, expired)}")

    def test_environment_can_enable_static_and_signed_auth_together(self) -> None:
        authenticator = authenticator_from_environ(
            {
                "TITAN_ADMIN_TOKEN": "this-is-a-long-static-admin-token",
                "TITAN_JWT_SECRET": self.SECRET,
            }
        )
        self.assertEqual(
            "bootstrap-admin",
            authenticator.authenticate("Bearer this-is-a-long-static-admin-token").subject,
        )
        self.assertEqual(
            "workload:catalog",
            authenticator.authenticate(f"Bearer {token(self.SECRET, self.claims())}").subject,
        )


if __name__ == "__main__":
    unittest.main()

