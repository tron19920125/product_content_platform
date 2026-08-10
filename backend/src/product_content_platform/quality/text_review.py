from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


BBox = tuple[float, float, float, float]

NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9])\d+(?:\.\d+)?(?:\s*[xX×*]\s*\d+(?:\.\d+)?)*"
    r"(?:\s*(?:°C|mm|cm|kg|dB|元|年|天|期|折|%|万|万元|分钟|秒|h|H))?"
)


@dataclass(frozen=True)
class OcrLine:
    text: str
    confidence: float | None = None
    bbox: BBox | None = None


@dataclass(frozen=True)
class TextReviewSpec:
    required_text: list[str] = field(default_factory=list)
    forbidden_text: list[str] = field(default_factory=list)
    number_allowlist: list[str] = field(default_factory=list)
    strict_number_allowlist: bool = False
    min_confidence: float | None = None
    expected_text_region: BBox | None = None
    task_id: str = "text-review"
    image_path: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TextReviewSpec":
        return cls(
            required_text=list(data.get("required_text", [])),
            forbidden_text=list(data.get("forbidden_text", [])),
            number_allowlist=list(data.get("number_allowlist", [])),
            strict_number_allowlist=bool(data.get("strict_number_allowlist", False)),
            min_confidence=data.get("min_confidence"),
            expected_text_region=parse_bbox(data.get("expected_text_region")),
            task_id=str(data.get("task_id", "text-review")),
            image_path=str(data.get("image_path", "")),
        )


@dataclass(frozen=True)
class TextReviewResult:
    status: str
    severity: str
    issues: list[dict[str, Any]]
    extracted_text: str
    normalized_text: str
    extracted_numbers: list[str]
    checked: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "severity": self.severity,
            "issues": self.issues,
            "extracted_text": self.extracted_text,
            "normalized_text": self.normalized_text,
            "extracted_numbers": self.extracted_numbers,
            "checked": self.checked,
        }


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return re.sub(r"\s+", "", normalized).casefold()


def normalize_required_text(value: str) -> str:
    """Normalize OCR copy matching while ignoring punctuation OCR commonly drops."""
    return re.sub(r"[^\w]+", "", normalize_text(value), flags=re.UNICODE)


def normalize_number(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return re.sub(r"\s+", "", normalized)


def parse_bbox(value: Any) -> BBox | None:
    if value is None:
        return None
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        x1, y1, x2, y2 = (float(item) for item in value)
    except (TypeError, ValueError):
        return None
    return (
        max(0.0, min(1.0, min(x1, x2))),
        max(0.0, min(1.0, min(y1, y2))),
        max(0.0, min(1.0, max(x1, x2))),
        max(0.0, min(1.0, max(y1, y2))),
    )


def bbox_center_inside_region(bbox: BBox, region: BBox) -> bool:
    x1, y1, x2, y2 = bbox
    rx1, ry1, rx2, ry2 = region
    center_x = (x1 + x2) / 2
    center_y = (y1 + y2) / 2
    return rx1 <= center_x <= rx2 and ry1 <= center_y <= ry2


def extract_numbers(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", text)
    numbers = []
    seen = set()
    for match in NUMBER_RE.finditer(normalized):
        number = normalize_number(match.group(0))
        if number and number not in seen:
            seen.add(number)
            numbers.append(number)
    return numbers


def review_text_ocr(lines: list[OcrLine], spec: TextReviewSpec) -> TextReviewResult:
    extracted_text = "\n".join(line.text for line in lines)
    normalized_text = normalize_text(extracted_text)
    issues: list[dict[str, Any]] = []

    for expected in spec.required_text:
        normalized_expected = normalize_required_text(expected)
        normalized_required_source = normalize_required_text(extracted_text)
        if normalized_expected not in normalized_required_source:
            issues.append(
                {
                    "code": "missing_required_text",
                    "severity": "P1",
                    "expected": expected,
                    "message": f"Required text was not found: {expected}",
                }
            )
        elif spec.expected_text_region is not None:
            matching_lines = [
                line for line in lines
                if normalized_expected in normalize_required_text(line.text)
            ]
            for line in matching_lines:
                if line.bbox is None:
                    issues.append(
                        {
                            "code": "required_text_missing_bbox",
                            "severity": "P2",
                            "text": line.text,
                            "message": f"Required text has no OCR bounding box: {line.text}",
                        }
                    )
                elif not bbox_center_inside_region(line.bbox, spec.expected_text_region):
                    issues.append(
                        {
                            "code": "required_text_outside_expected_region",
                            "severity": "P1",
                            "text": line.text,
                            "bbox": line.bbox,
                            "expected_region": spec.expected_text_region,
                            "message": f"Required text is outside expected region: {line.text}",
                        }
                    )

    for forbidden in spec.forbidden_text:
        if normalize_text(forbidden) in normalized_text:
            issues.append(
                {
                    "code": "forbidden_text_detected",
                    "severity": "P1",
                    "text": forbidden,
                    "message": f"Forbidden text was detected: {forbidden}",
                }
            )

    # Numeric fact checks belong to the post-composed copy area. Numbers printed
    # on the photographed product (for example a timer on an appliance panel)
    # are product/reference evidence, not marketing-copy facts.
    number_lines = lines
    if spec.expected_text_region is not None:
        number_lines = [
            line
            for line in lines
            if line.bbox is None or bbox_center_inside_region(line.bbox, spec.expected_text_region)
        ]
    extracted_numbers = extract_numbers("\n".join(line.text for line in number_lines))
    if spec.strict_number_allowlist:
        allowed = {normalize_number(item) for item in spec.number_allowlist}
        for number in extracted_numbers:
            if number not in allowed:
                issues.append(
                    {
                        "code": "unapproved_number_detected",
                        "severity": "P1",
                        "number": number,
                        "message": f"Number is not in allowlist: {number}",
                    }
                )

    if spec.min_confidence is not None:
        for line in lines:
            if line.confidence is not None and line.confidence < spec.min_confidence:
                issues.append(
                    {
                        "code": "low_ocr_confidence",
                        "severity": "P2",
                        "text": line.text,
                        "confidence": line.confidence,
                        "message": f"OCR confidence is below threshold: {line.confidence}",
                    }
                )

    status = "pass"
    severity = "P3"
    if any(issue["severity"] in {"P0", "P1"} for issue in issues):
        status = "fail"
        severity = "P1"
    elif issues:
        status = "review"
        severity = "P2"

    return TextReviewResult(
        status=status,
        severity=severity,
        issues=issues,
        extracted_text=extracted_text,
        normalized_text=normalized_text,
        extracted_numbers=extracted_numbers,
        checked={
            "required_text": spec.required_text,
            "forbidden_text": spec.forbidden_text,
            "number_allowlist": spec.number_allowlist,
            "strict_number_allowlist": spec.strict_number_allowlist,
            "min_confidence": spec.min_confidence,
            "expected_text_region": spec.expected_text_region,
            "number_scope": "expected_text_region" if spec.expected_text_region is not None else "whole_image",
        },
    )


def load_spec(path: str | Path) -> TextReviewSpec:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return TextReviewSpec.from_dict(data)


def load_ocr_lines(path: str | Path) -> list[OcrLine]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict) and "lines" in data:
        rows = data["lines"]
    elif isinstance(data, list):
        rows = data
    else:
        rows = _lines_from_azure_read(data)
    return [
        OcrLine(text=str(row.get("text", "")), confidence=row.get("confidence"), bbox=parse_bbox(row.get("bbox")))
        for row in rows
    ]


def _lines_from_azure_read(data: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = data.get("readResult", {}).get("blocks", [])
    lines = []
    for block in blocks:
        for row in block.get("lines", []):
            lines.append({"text": row.get("text", ""), "confidence": row.get("confidence"), "bbox": row.get("bbox")})
    return lines


def write_result_json(path: str | Path, result: TextReviewResult) -> None:
    Path(path).write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def render_markdown_report(result: TextReviewResult, spec: TextReviewSpec) -> str:
    lines = [
        f"# OCR Text Review - {spec.task_id}",
        "",
        f"- Status: `{result.status}`",
        f"- Severity: `{result.severity}`",
        f"- Image: `{spec.image_path or 'not provided'}`",
        "",
        "## Issues",
        "",
    ]
    if result.issues:
        for issue in result.issues:
            lines.append(f"- `{issue['severity']}` `{issue['code']}`: {issue['message']}")
    else:
        lines.append("- No issues detected.")
    lines.extend(
        [
            "",
            "## Extracted Text",
            "",
            "```text",
            result.extracted_text,
            "```",
            "",
            "## Extracted Numbers",
            "",
        ]
    )
    if result.extracted_numbers:
        lines.extend(f"- `{number}`" for number in result.extracted_numbers)
    else:
        lines.append("- No numbers detected.")
    return "\n".join(lines) + "\n"


def write_markdown_report(path: str | Path, result: TextReviewResult, spec: TextReviewSpec) -> None:
    Path(path).write_text(render_markdown_report(result, spec), encoding="utf-8")
