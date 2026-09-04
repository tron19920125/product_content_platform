from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .catalog import StrictModel


class Finding(StrictModel):
    kind: Literal["error", "uncertain", "suggestion"]
    message: str = Field(min_length=1, max_length=2000)
    evidence: str = Field(default="", max_length=4000)
    critical: bool = False

    @model_validator(mode="after")
    def critical_requires_evidence(self):
        if self.critical and (self.kind != "error" or not self.evidence.strip()):
            raise ValueError("关键错误必须有明确证据，疑点或建议不能当作关键错误")
        return self


class Review(StrictModel):
    status: Literal["completed", "unavailable", "checking"] = "unavailable"
    product: float | None = Field(default=None, ge=0, le=100)
    copywriting: float | None = Field(default=None, ge=0, le=100)
    layout: float | None = Field(default=None, ge=0, le=100)
    brand: float | None = Field(default=None, ge=0, le=100)
    findings: list[Finding] = Field(default_factory=list, max_length=30)
    source: str = Field(default="", max_length=200)
    note: str = Field(default="", max_length=4000)

    @property
    def score(self) -> float | None:
        if self.status != "completed":
            return None
        weights = {"product": .35, "copywriting": .30, "layout": .25, "brand": .10}
        applicable = [(getattr(self, key), weight) for key, weight in weights.items() if getattr(self, key) is not None]
        if not applicable:
            return None
        result = round(sum(value * weight for value, weight in applicable) / sum(weight for _, weight in applicable), 1)
        return min(59, result) if any(item.critical for item in self.findings) else result

    def public(self) -> dict:
        return {**self.model_dump(mode="json"), "score": self.score}


def should_repair(review: Review, *, repair_used: bool, stopped: bool = False) -> bool:
    return not repair_used and not stopped and review.score is not None and review.score < 60
