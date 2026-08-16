"""In-cluster adapter for the deterministic TitanService reconciliation plan."""

from __future__ import annotations

import json
import logging
import os
import signal
import ssl
import threading
import time
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from typing import Any, Mapping, Protocol
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from titan_operator.reconcile import (
    FINALIZER,
    OperatorValidationError,
    ReconcilePlan,
    plan_service_reconciliation,
)

LOGGER = logging.getLogger("titan.operator")
SERVICE_ACCOUNT_ROOT = Path("/var/run/secrets/kubernetes.io/serviceaccount")


class KubernetesAPIError(RuntimeError):
    """A bounded, sanitized Kubernetes API failure."""

    def __init__(self, method: str, path: str, status: int, reason: str) -> None:
        super().__init__(f"Kubernetes API {method} {path} failed ({status}): {reason}")
        self.status = status


class OperatorAPI(Protocol):
    def list_services(self) -> list[Mapping[str, Any]]: ...

    def get_deployment(self, name: str, namespace: str) -> Mapping[str, Any] | None: ...

    def patch_finalizers(self, resource: Mapping[str, Any], finalizers: list[str]) -> None: ...

    def apply_deployment(
        self, deployment: Mapping[str, Any], owner: Mapping[str, Any]
    ) -> None: ...

    def delete_deployment(self, name: str, namespace: str) -> None: ...

    def patch_status(self, resource: Mapping[str, Any], status: Mapping[str, Any]) -> None: ...


@dataclass(frozen=True, slots=True)
class KubernetesConfig:
    server: str
    namespace: str
    token: str
    ca_file: Path
    timeout_seconds: float = 10.0

    @classmethod
    def in_cluster(
        cls,
        environ: Mapping[str, str] | None = None,
        service_account_root: Path = SERVICE_ACCOUNT_ROOT,
    ) -> "KubernetesConfig":
        source = os.environ if environ is None else environ
        host = source.get("KUBERNETES_SERVICE_HOST", "").strip()
        port = source.get("KUBERNETES_SERVICE_PORT_HTTPS", "443").strip()
        namespace = source.get("POD_NAMESPACE", "").strip()
        token_path = service_account_root / "token"
        namespace_path = service_account_root / "namespace"
        ca_path = service_account_root / "ca.crt"
        if not namespace and namespace_path.exists():
            namespace = namespace_path.read_text(encoding="utf-8").strip()
        if not host or not namespace or not token_path.is_file() or not ca_path.is_file():
            raise ValueError("in-cluster Kubernetes host, namespace, token and CA are required")
        return cls(
            server=f"https://{host}:{port}",
            namespace=namespace,
            token=token_path.read_text(encoding="utf-8").strip(),
            ca_file=ca_path,
            timeout_seconds=_bounded_float(
                source.get("TITAN_OPERATOR_API_TIMEOUT_SECONDS", "10"), 1.0, 60.0
            ),
        )


class KubernetesAPI:
    """Small Kubernetes REST client with no cluster-admin or external dependency."""

    def __init__(self, config: KubernetesConfig) -> None:
        self.config = config
        self._ssl_context = ssl.create_default_context(cafile=str(config.ca_file))

    def list_services(self) -> list[Mapping[str, Any]]:
        document = self._request("GET", self._service_collection_path())
        items = document.get("items", [])
        if not isinstance(items, list) or not all(isinstance(item, Mapping) for item in items):
            raise KubernetesAPIError("GET", self._service_collection_path(), 502, "invalid list response")
        return items

    def get_deployment(self, name: str, namespace: str) -> Mapping[str, Any] | None:
        path = self._deployment_path(name, namespace)
        try:
            return self._request("GET", path)
        except KubernetesAPIError as error:
            if error.status == HTTPStatus.NOT_FOUND:
                return None
            raise

    def patch_finalizers(self, resource: Mapping[str, Any], finalizers: list[str]) -> None:
        metadata = _metadata(resource)
        payload = {
            "metadata": {
                "resourceVersion": metadata.get("resourceVersion"),
                "finalizers": finalizers,
            }
        }
        self._request(
            "PATCH",
            self._service_path(str(metadata["name"])),
            payload,
            content_type="application/merge-patch+json",
        )

    def apply_deployment(
        self, deployment: Mapping[str, Any], owner: Mapping[str, Any]
    ) -> None:
        desired = json.loads(json.dumps(deployment))
        owner_metadata = _metadata(owner)
        desired_metadata = desired.setdefault("metadata", {})
        desired_metadata["ownerReferences"] = [
            {
                "apiVersion": "platform.titan.dev/v1alpha1",
                "kind": "TitanService",
                "name": owner_metadata["name"],
                "uid": owner_metadata["uid"],
                "controller": True,
                "blockOwnerDeletion": True,
            }
        ]
        namespace = str(desired_metadata["namespace"])
        name = str(desired_metadata["name"])
        query = urlencode({"fieldManager": "titan-operator", "force": "false"})
        self._request(
            "PATCH",
            f"{self._deployment_path(name, namespace)}?{query}",
            desired,
            content_type="application/apply-patch+yaml",
        )

    def delete_deployment(self, name: str, namespace: str) -> None:
        try:
            self._request(
                "DELETE",
                self._deployment_path(name, namespace),
                {
                    "apiVersion": "v1",
                    "kind": "DeleteOptions",
                    "propagationPolicy": "Foreground",
                },
            )
        except KubernetesAPIError as error:
            if error.status != HTTPStatus.NOT_FOUND:
                raise

    def patch_status(self, resource: Mapping[str, Any], status: Mapping[str, Any]) -> None:
        metadata = _metadata(resource)
        self._request(
            "PATCH",
            f"{self._service_path(str(metadata['name']))}/status",
            {
                "metadata": {"resourceVersion": metadata.get("resourceVersion")},
                "status": status,
            },
            content_type="application/merge-patch+json",
        )

    def _request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
        *,
        content_type: str = "application/json",
    ) -> Mapping[str, Any]:
        body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
        request = Request(
            f"{self.config.server}{path}",
            data=body,
            method=method,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.config.token}",
                "Content-Type": content_type,
                "User-Agent": "titan-operator/0.1.0",
            },
        )
        try:
            with urlopen(
                request,
                timeout=self.config.timeout_seconds,
                context=self._ssl_context,
            ) as response:
                raw = response.read(1_048_577)
                if len(raw) > 1_048_576:
                    raise KubernetesAPIError(method, path, 502, "response exceeded 1 MiB")
                if not raw:
                    return {}
                document = json.loads(raw)
                if not isinstance(document, Mapping):
                    raise KubernetesAPIError(method, path, 502, "response was not an object")
                return document
        except HTTPError as error:
            reason = error.reason if isinstance(error.reason, str) else HTTPStatus(error.code).phrase
            raise KubernetesAPIError(method, path, error.code, reason) from error
        except (json.JSONDecodeError, OSError) as error:
            raise KubernetesAPIError(method, path, 502, type(error).__name__) from error

    def _service_collection_path(self) -> str:
        namespace = quote(self.config.namespace, safe="")
        return f"/apis/platform.titan.dev/v1alpha1/namespaces/{namespace}/titanservices"

    def _service_path(self, name: str) -> str:
        return f"{self._service_collection_path()}/{quote(name, safe='')}"

    @staticmethod
    def _deployment_path(name: str, namespace: str) -> str:
        return f"/apis/apps/v1/namespaces/{quote(namespace, safe='')}/deployments/{quote(name, safe='')}"


class OperatorController:
    """Executes plans, rate-limits requeues and isolates per-resource failures."""

    def __init__(self, api: OperatorAPI) -> None:
        self.api = api
        self._next_due: dict[str, float] = {}

    def reconcile_all(self, *, now: float | None = None) -> tuple[int, int]:
        current = time.monotonic() if now is None else now
        reconciled = 0
        failed = 0
        resources = self.api.list_services()
        live_keys: set[str] = set()
        for resource in resources:
            key = _resource_key(resource)
            live_keys.add(key)
            if self._next_due.get(key, 0.0) > current:
                continue
            try:
                plan = self._reconcile_one(resource)
                reconciled += 1
                self._next_due[key] = current + (plan.requeue_after_seconds or 30)
            except OperatorValidationError as error:
                failed += 1
                self._next_due[key] = current + 30
                LOGGER.warning(
                    "TitanService specification rejected: %s",
                    error,
                    extra={"resource": key},
                )
            except (KubernetesAPIError, KeyError, TypeError, ValueError):
                failed += 1
                self._next_due[key] = current + 10
                LOGGER.exception("TitanService reconciliation failed", extra={"resource": key})
        self._next_due = {key: due for key, due in self._next_due.items() if key in live_keys}
        return reconciled, failed

    def _reconcile_one(self, resource: Mapping[str, Any]) -> ReconcilePlan:
        metadata = _metadata(resource)
        name = str(metadata["name"])
        namespace = str(metadata.get("namespace", "default"))
        child = self.api.get_deployment(name, namespace)
        try:
            plan = plan_service_reconciliation(resource, child_deployment=child)
        except OperatorValidationError as error:
            status = {
                "observedGeneration": int(metadata.get("generation", 1)),
                "conditions": [
                    {
                        "type": "Ready",
                        "status": "False",
                        "reason": "InvalidSpec",
                        "message": str(error),
                    }
                ],
            }
            if resource.get("status") != status:
                self.api.patch_status(resource, status)
            raise

        finalizers = [str(item) for item in metadata.get("finalizers", [])]
        for action in plan.actions:
            if action.kind == "add-finalizer":
                if FINALIZER not in finalizers:
                    self.api.patch_finalizers(resource, [*finalizers, FINALIZER])
                    # Persist deletion protection before creating owned resources.
                    # The patch advances resourceVersion, so status must wait for
                    # the fresh object returned by the next reconciliation pass.
                    return plan
            elif action.kind == "remove-finalizer":
                self.api.patch_finalizers(resource, [item for item in finalizers if item != FINALIZER])
                # The API server may delete the parent immediately after this patch.
                return plan
            elif action.kind == "apply-child":
                self.api.apply_deployment(action.payload, resource)
            elif action.kind == "delete-child":
                self.api.delete_deployment(name, namespace)
            else:
                raise OperatorValidationError(f"unsupported operator action: {action.kind}")
        if resource.get("status") != plan.status:
            self.api.patch_status(resource, plan.status)
        return plan


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("TITAN_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    config = KubernetesConfig.in_cluster()
    controller = OperatorController(KubernetesAPI(config))
    interval = _bounded_float(os.environ.get("TITAN_OPERATOR_POLL_SECONDS", "2"), 0.5, 60.0)
    stop = threading.Event()

    def request_stop(signum: int, _frame: object) -> None:
        LOGGER.info("operator shutdown requested", extra={"signal": signum})
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    failures = 0
    while not stop.is_set():
        try:
            reconciled, failed = controller.reconcile_all()
            failures = failures + 1 if failed else 0
            LOGGER.info("operator pass complete", extra={"reconciled": reconciled, "failed": failed})
        except KubernetesAPIError:
            failures += 1
            LOGGER.exception("operator list failed")
        backoff = min(30.0, interval * (2 ** min(failures, 4)))
        stop.wait(backoff)


def _metadata(resource: Mapping[str, Any]) -> Mapping[str, Any]:
    metadata = resource.get("metadata")
    if not isinstance(metadata, Mapping) or not metadata.get("name"):
        raise ValueError("resource metadata.name is required")
    return metadata


def _resource_key(resource: Mapping[str, Any]) -> str:
    metadata = _metadata(resource)
    fallback = f"{metadata.get('namespace', 'default')}/{metadata['name']}"
    return str(metadata.get("uid") or fallback)


def _bounded_float(raw: str, minimum: float, maximum: float) -> float:
    value = float(raw)
    if not minimum <= value <= maximum:
        raise ValueError(f"value must be between {minimum} and {maximum}")
    return value


if __name__ == "__main__":
    main()
