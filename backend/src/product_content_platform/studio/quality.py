from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .catalog import StrictModel


class Finding(StrictModel):
    kind: Literal["error", "uncertain", "suggestion"]
    message: str = Field(min_length=1, max_length=2000)
    evidence: str = Field(default="", max_length=4000)
    action: str = Field(default="", max_length=2000)

    @model_validator(mode="before")
    @classmethod
    def read_legacy_finding(cls, value):
        if isinstance(value, dict):
            value = {key: item for key, item in value.items() if key != "critical"}
        return value

    @model_validator(mode="after")
    def uncertain_is_not_an_edit(self):
        if self.kind == "uncertain":
            self.action = ""
        if self.kind == "error" and self.action and not self.evidence.strip():
            raise ValueError("按明确问题修复需要可核对的依据")
        return self


class Review(StrictModel):
    status: Literal["completed", "unavailable", "checking"] = "unavailable"
    summary: str = Field(default="", max_length=2000)
    strengths: list[str] = Field(default_factory=list, max_length=5)
    copy_observation: str = Field(default="", max_length=2000)
    findings: list[Finding] = Field(default_factory=list, max_length=30)
    source: str = Field(default="", max_length=200)
    note: str = Field(default="", max_length=4000)

    @model_validator(mode="before")
    @classmethod
    def read_legacy_review(cls, value):
        # Old records remain readable; numeric ratings never leave this boundary.
        if isinstance(value, dict):
            legacy = any(key in value for key in ("product", "copywriting", "layout", "brand", "score"))
            value = {key: item for key, item in value.items() if key not in {"product", "copywriting", "layout", "brand", "score"}}
            if legacy and value.get("status") == "completed" and not value.get("summary"):
                value["summary"] = (value.get("note") or "历史点评可供参考，可重新点评以获得具体修改建议。")[:2000]
        return value

    @property
    def repair_actions(self) -> list[str]:
        if self.status != "completed":
            return []
        return list(dict.fromkeys(item.action.strip() for item in self.findings
                                 if item.kind != "uncertain" and item.action.strip()))

    def public(self) -> dict:
        return self.model_dump(mode="json")
