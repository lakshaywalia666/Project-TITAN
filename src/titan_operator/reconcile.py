"""Pure operator planning logic, separated from the Kubernetes client boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

FINALIZER = "platform.titan.dev/managed-resource"


class OperatorValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class OperatorAction:
    kind: str
    payload: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ReconcilePlan:
    actions: tuple[OperatorAction, ...]
    status: Mapping[str, Any]
    requeue_after_seconds: int | None = None


def plan_service_reconciliation(
    resource: Mapping[str, Any],
    *,
    child_deployment: Mapping[str, Any] | None,
    provider_ready: bool = True,
) -> ReconcilePlan:
    metadata = _mapping(resource.get("metadata"), "metadata")
    spec = _mapping(resource.get("spec"), "spec")
    name = str(metadata.get("name", ""))
    namespace = str(metadata.get("namespace", "default"))
    generation = int(metadata.get("generation", 1))
    deletion_timestamp = metadata.get("deletionTimestamp")
    finalizers = tuple(str(item) for item in metadata.get("finalizers", []))
    if not name:
        raise OperatorValidationError("metadata.name is required")
    image = str(spec.get("image", ""))
    replicas = int(spec.get("replicas", 1))
    port = int(spec.get("port", 8080))
    if not image or image.endswith(":latest"):
        raise OperatorValidationError("spec.image must be explicit and must not use latest")
    if not 1 <= replicas <= 20 or not 1 <= port <= 65_535:
        raise OperatorValidationError("replicas or port is outside the supported range")

    if deletion_timestamp:
        if FINALIZER not in finalizers:
            return ReconcilePlan((), _condition(generation, "Deleting", "False", "Finalized"))
        if child_deployment is not None:
            return ReconcilePlan(
                (OperatorAction("delete-child", {"kind": "Deployment", "name": name, "namespace": namespace}),),
                _condition(generation, "Deleting", "False", "CleanupInProgress"),
                requeue_after_seconds=2,
            )
        return ReconcilePlan(
            (OperatorAction("remove-finalizer", {"finalizer": FINALIZER}),),
            _condition(generation, "Deleting", "False", "CleanupComplete"),
        )

    actions: list[OperatorAction] = []
    if FINALIZER not in finalizers:
        actions.append(OperatorAction("add-finalizer", {"finalizer": FINALIZER}))
    desired_child = _deployment(name, namespace, image, replicas, port, generation)
    if not _child_matches(child_deployment, desired_child):
        actions.append(OperatorAction("apply-child", desired_child))
    if not provider_ready:
        return ReconcilePlan(
            tuple(actions),
            _condition(generation, "Ready", "False", "ExternalProviderPending"),
            requeue_after_seconds=10,
        )
    ready_replicas = int(
        _mapping((child_deployment or {}).get("status", {}), "child status").get(
            "readyReplicas", 0
        )
    )
    ready = child_deployment is not None and ready_replicas >= replicas and not actions[-1:] == [OperatorAction("apply-child", desired_child)]
    return ReconcilePlan(
        tuple(actions),
        _condition(
            generation,
            "Ready",
            "True" if ready else "False",
            "Available" if ready else "Reconciling",
        ),
        None if ready else 2,
    )


def _deployment(
    name: str, namespace: str, image: str, replicas: int, port: int, generation: int
) -> dict[str, Any]:
    labels = {"app.kubernetes.io/name": name, "platform.titan.dev/managed": "true"}
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": labels,
            "annotations": {"platform.titan.dev/generation": str(generation)},
        },
        "spec": {
            "replicas": replicas,
            "selector": {"matchLabels": {"app.kubernetes.io/name": name}},
            "template": {
                "metadata": {"labels": labels},
                "spec": {
                    "automountServiceAccountToken": False,
                    "securityContext": {"runAsNonRoot": True, "seccompProfile": {"type": "RuntimeDefault"}},
                    "containers": [
                        {
                            "name": "application",
                            "image": image,
                            "ports": [{"name": "http", "containerPort": port}],
                            "securityContext": {
                                "allowPrivilegeEscalation": False,
                                "readOnlyRootFilesystem": True,
                                "capabilities": {"drop": ["ALL"]},
                            },
                            "resources": {
                                "requests": {"cpu": "50m", "memory": "64Mi"},
                                "limits": {"cpu": "500m", "memory": "512Mi"},
                            },
                        }
                    ],
                },
            },
        },
    }


def _child_matches(
    actual: Mapping[str, Any] | None, desired: Mapping[str, Any]
) -> bool:
    if actual is None:
        return False
    actual_metadata = _mapping(actual.get("metadata"), "child metadata")
    desired_metadata = _mapping(desired["metadata"], "desired child metadata")
    if actual_metadata.get("annotations", {}).get("platform.titan.dev/generation") != desired_metadata.get("annotations", {}).get("platform.titan.dev/generation"):
        return False
    actual_spec = _mapping(actual.get("spec"), "child spec")
    desired_spec = _mapping(desired["spec"], "desired child spec")
    return (
        actual_spec.get("replicas") == desired_spec.get("replicas")
        and _first_image(actual_spec) == _first_image(desired_spec)
    )


def _first_image(spec: Mapping[str, Any]) -> str | None:
    try:
        return str(spec["template"]["spec"]["containers"][0]["image"])
    except (KeyError, IndexError, TypeError):
        return None


def _condition(
    generation: int, condition_type: str, status: str, reason: str
) -> dict[str, Any]:
    return {
        "observedGeneration": generation,
        "conditions": [
            {
                "type": condition_type,
                "status": status,
                "reason": reason,
                "observedGeneration": generation,
            }
        ],
    }


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise OperatorValidationError(f"{name} must be an object")
    return value

