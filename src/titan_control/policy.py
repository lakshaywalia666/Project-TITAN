"""Authorization policy kept outside resource reconciliation logic."""

from __future__ import annotations

from dataclasses import dataclass

from titan_control.domain import Identity


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    reason: str


class PolicyEngine:
    READ_ACTIONS = {
        "project:list",
        "project:get",
        "resource:list",
        "resource:get",
        "operation:list",
        "audit:list",
    }
    PROJECT_WRITE_ACTIONS = {
        "resource:create",
        "resource:update",
        "resource:delete",
    }

    def decide(
        self, identity: Identity, action: str, project_id: str | None = None
    ) -> PolicyDecision:
        roles = set(identity.roles)

        if "admin" in roles:
            return PolicyDecision(True, "admin role")

        if action == "project:create":
            return PolicyDecision(False, "project creation requires admin role")

        if "platform_operator" in roles:
            if action in self.READ_ACTIONS | self.PROJECT_WRITE_ACTIONS:
                return PolicyDecision(True, "platform operator role")

        project_member = project_id is not None and project_id in identity.project_ids

        if "developer" in roles and project_member:
            if action in self.READ_ACTIONS | self.PROJECT_WRITE_ACTIONS:
                return PolicyDecision(True, "developer is a project member")

        if "viewer" in roles and project_member and action in self.READ_ACTIONS:
            return PolicyDecision(True, "viewer has project read access")

        if "agent" in roles and project_member and action in self.READ_ACTIONS:
            return PolicyDecision(True, "agent has read-only project access")

        return PolicyDecision(False, "no policy rule grants this action")

