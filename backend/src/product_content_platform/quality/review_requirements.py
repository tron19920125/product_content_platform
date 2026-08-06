from __future__ import annotations

from typing import Any, Mapping


REQUIREMENT_FIELDS = (
    ("must_appear", "appear", "必须出现"),
    ("must_not_appear", "remove", "必须移除"),
    ("must_preserve", "preserve", "必须保留"),
    ("review_checks", "check", "重点检查"),
)


def build_review_requirements(plan: Mapping[str, Any] | None) -> list[dict[str, str]]:
    if not isinstance(plan, Mapping):
        return []
    requirements: list[dict[str, str]] = []
    for field, prefix, label in REQUIREMENT_FIELDS:
        values = plan.get(field)
        if not isinstance(values, (list, tuple)):
            continue
        for index, value in enumerate(values, start=1):
            text = str(value).strip()
            if not text:
                continue
            requirements.append(
                {
                    "id": f"{prefix}-{index:03d}",
                    "type": field,
                    "label": label,
                    "text": text,
                }
            )
    return requirements


def requirements_with_fallback(plan: Mapping[str, Any] | None) -> list[dict[str, str]]:
    if not isinstance(plan, Mapping):
        return []
    generated = build_review_requirements(plan)
    if generated:
        return generated
    existing = plan.get("requirements")
    if not isinstance(existing, list):
        return []
    normalized = []
    for item in existing:
        if not isinstance(item, Mapping):
            continue
        requirement_id = str(item.get("id") or "").strip()
        text = str(item.get("text") or "").strip()
        if not requirement_id or not text:
            continue
        normalized.append(
            {
                "id": requirement_id,
                "type": str(item.get("type") or "review_checks").strip(),
                "label": str(item.get("label") or "审查要求").strip(),
                "text": text,
            }
        )
    return normalized
