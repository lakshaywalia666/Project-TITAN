"""Transparent deterministic fraud model used by the Titan Shop simulator."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FraudFeatures:
    amount_paise: int
    account_age_days: int
    orders_last_hour: int
    country_mismatch: bool = False


@dataclass(frozen=True, slots=True)
class FraudPrediction:
    score: float
    decision: str
    model_version: str
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "score": self.score,
            "decision": self.decision,
            "model_version": self.model_version,
            "reasons": list(self.reasons),
        }


class FraudModel:
    """A tiny explainable scorer; it is a serving workload, not a claim of ML quality."""

    version = "fraud-linear-1"

    def predict(self, features: FraudFeatures) -> FraudPrediction:
        if features.amount_paise < 0 or features.account_age_days < 0 or features.orders_last_hour < 0:
            raise ValueError("fraud features must be non-negative")
        reasons: list[str] = []
        logit = -3.2
        amount_rupees = features.amount_paise / 100
        logit += min(amount_rupees / 30_000, 2.0)
        if amount_rupees >= 20_000:
            reasons.append("high_amount")
        if features.account_age_days < 7:
            logit += 1.1
            reasons.append("new_account")
        if features.orders_last_hour >= 5:
            logit += 1.5
            reasons.append("high_velocity")
        if features.country_mismatch:
            logit += 1.8
            reasons.append("country_mismatch")
        score = 1 / (1 + math.exp(-logit))
        decision = "deny" if score >= 0.65 else "review" if score >= 0.42 else "allow"
        return FraudPrediction(round(score, 6), decision, self.version, tuple(reasons))
