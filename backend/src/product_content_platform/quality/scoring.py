from __future__ import annotations

from dataclasses import dataclass
from typing import Any


STATUS_BASE_SCORE = {"pass": 94, "review": 76, "fail": 48}
STATUS_SCORE_CAP = {"pass": 100, "review": 89, "fail": 59}


@dataclass(frozen=True)
class WorkflowRequest:
    mode: str
    prompt: str
    output_size: str
    quality: str
    candidate_count: int = 3
    auto_repair: bool = True
    review_plan_override: dict[str, Any] | None = None
    source_image_path: str = ""
    product_reference_image_path: str = ""


def score_candidate(review_payload: dict[str, Any], visual_review: dict[str, Any] | None = None) -> dict[str, Any]:
    status = str(review_payload.get("status") or "review").casefold()
    if status not in STATUS_BASE_SCORE:
        status = "review"
    confidence = _clamp_float(review_payload.get("confidence"), 0.0, 1.0, 0.0)
    score_breakdown = _score_breakdown(review_payload.get("score_breakdown"), visual_review)
    category_score = sum(score_breakdown.values()) / max(1, len(score_breakdown))
    status_score = STATUS_BASE_SCORE[status]
    score = round((category_score * 0.65) + (status_score * 0.2) + (confidence * 100 * 0.15))
    score = min(score, STATUS_SCORE_CAP[status])
    if status == "pass":
        score = max(score, 80)
    return {"overall": int(max(0, min(100, score))), "breakdown": score_breakdown}


def rank_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(
        candidates,
        key=lambda candidate: (
            int(candidate.get("score", {}).get("overall", 0)),
            _status_rank(candidate.get("result", {}).get("status")),
            float(candidate.get("llm_review", {}).get("confidence", 0.0)),
        ),
        reverse=True,
    )
    for index, candidate in enumerate(ordered, start=1):
        candidate["rank"] = index
        candidate["recommended"] = index == 1
    return ordered


def compose_repair_prompt(original_prompt: str, suggested_fix: str, plan: dict[str, Any]) -> str:
    preserve = "；".join(str(item) for item in plan.get("must_preserve", []) if str(item).strip())
    required = "；".join(str(item) for item in plan.get("must_appear", []) if str(item).strip())
    forbidden = "；".join(str(item) for item in plan.get("must_not_appear", []) if str(item).strip())
    sections = [
        original_prompt.strip(),
        "这是一次自动修复。只修正审查发现的问题，不要改变已经正确的内容。",
        f"审查修复要求：{suggested_fix.strip() or '提高提示词符合度并修复未通过项。'}",
    ]
    if required:
        sections.append(f"必须准确满足：{required}")
    if forbidden:
        sections.append(f"必须移除或避免：{forbidden}")
    if preserve:
        sections.append(f"必须保持不变：{preserve}")
    return "\n\n".join(section for section in sections if section)


def _score_breakdown(value: Any, visual_review: dict[str, Any] | None) -> dict[str, int]:
    keys = ("text_accuracy", "product_consistency", "layout_stability", "brand_compliance")
    scores: dict[str, int] = {}
    if isinstance(value, dict):
        for key in keys:
            scores[key] = int(round(_clamp_float(value.get(key), 0.0, 100.0, 0.0)))
    if not scores or not any(scores.values()):
        scores = {key: 80 for key in keys}

    if visual_review:
        similarity = _clamp_float(visual_review.get("reference_similarity"), 0.0, 1.0, 0.0)
        outside_change = _clamp_float(visual_review.get("outside_target_change"), 0.0, 1.0, 1.0)
        if similarity and visual_review.get("comparison_scope") != "source_non_target_only":
            scores["product_consistency"] = round((scores["product_consistency"] + similarity * 100) / 2)
        scores["layout_stability"] = round(
            (scores["layout_stability"] + max(0.0, 1.0 - outside_change) * 100) / 2
        )
    return {key: int(max(0, min(100, scores[key]))) for key in keys}


def _status_rank(value: Any) -> int:
    return {"pass": 3, "review": 2, "fail": 1}.get(str(value or "review").casefold(), 0)


def _clamp_float(value: Any, low: float, high: float, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))
