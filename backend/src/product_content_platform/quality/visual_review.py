from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageStat


Region = tuple[float, float, float, float]


@dataclass(frozen=True)
class VisualReviewResult:
    status: str
    severity: str
    issues: list[dict[str, Any]]
    source_image: str
    output_image: str
    target_region: Region
    target_change: float
    outside_target_change: float
    reference_similarity: float
    checked: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "severity": self.severity,
            "issues": self.issues,
            "source_image": self.source_image,
            "output_image": self.output_image,
            "target_region": self.target_region,
            "target_change": self.target_change,
            "outside_target_change": self.outside_target_change,
            "reference_similarity": self.reference_similarity,
            "checked": self.checked,
        }


def review_edit_visuals(
    source_image: str | Path,
    output_image: str | Path,
    *,
    target_region: Region,
    min_target_change: float = 0.01,
    max_outside_change: float = 0.35,
    min_reference_similarity: float = 0.55,
    sample_size: int = 256,
) -> VisualReviewResult:
    source, output = _load_pair(source_image, output_image, sample_size)
    target_box = _region_to_box(target_region, source.size)
    target_change = _mean_abs_diff(source, output, target_box)
    outside_target_change = _mean_abs_diff_outside(source, output, target_box)
    reference_similarity = max(0.0, min(1.0, 1.0 - outside_target_change))

    issues: list[dict[str, Any]] = []
    if target_change < min_target_change:
        issues.append(
            _issue(
                "target_region_unchanged",
                "P2",
                "Target edit region did not change enough.",
                "target_change",
                target_change,
                min_target_change,
            )
        )
    if outside_target_change > max_outside_change:
        issues.append(
            _issue(
                "outside_target_changed",
                "P2",
                "Non-target image area changed more than expected.",
                "outside_target_change",
                outside_target_change,
                max_outside_change,
            )
        )
    if reference_similarity < min_reference_similarity:
        issues.append(
            _issue(
                "reference_similarity_low",
                "P2",
                "Edited image is not similar enough to the reference outside the target region.",
                "reference_similarity",
                reference_similarity,
                min_reference_similarity,
            )
        )

    status = "pass" if not issues else "review"
    severity = "P3" if not issues else "P2"
    return VisualReviewResult(
        status=status,
        severity=severity,
        issues=issues,
        source_image=str(source_image),
        output_image=str(output_image),
        target_region=target_region,
        target_change=target_change,
        outside_target_change=outside_target_change,
        reference_similarity=reference_similarity,
        checked={
            "min_target_change": min_target_change,
            "max_outside_change": max_outside_change,
            "min_reference_similarity": min_reference_similarity,
            "sample_size": sample_size,
        },
    )


def _issue(code: str, severity: str, message: str, metric: str, value: float, threshold: float) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "message": message,
        "metric": metric,
        "value": round(value, 4),
        "threshold": threshold,
    }


def _load_pair(source_image: str | Path, output_image: str | Path, sample_size: int) -> tuple[Image.Image, Image.Image]:
    source = Image.open(source_image).convert("RGB")
    output = Image.open(output_image).convert("RGB")
    if source.size == output.size and max(source.size) <= sample_size:
        return source, output
    return (
        source.resize((sample_size, sample_size), Image.Resampling.BOX),
        output.resize((sample_size, sample_size), Image.Resampling.BOX),
    )


def _region_to_box(region: Region, size: tuple[int, int]) -> tuple[int, int, int, int]:
    width, height = size
    x1, y1, x2, y2 = region
    left = int(max(0, min(width - 1, round(min(x1, x2) * width))))
    top = int(max(0, min(height - 1, round(min(y1, y2) * height))))
    right = int(max(left + 1, min(width, round(max(x1, x2) * width))))
    bottom = int(max(top + 1, min(height, round(max(y1, y2) * height))))
    return left, top, right, bottom


def _mean_abs_diff(source: Image.Image, output: Image.Image, box: tuple[int, int, int, int]) -> float:
    diff = ImageChops.difference(source.crop(box), output.crop(box))
    stat = ImageStat.Stat(diff)
    return sum(stat.mean) / (len(stat.mean) * 255.0)


def _mean_abs_diff_outside(source: Image.Image, output: Image.Image, target_box: tuple[int, int, int, int]) -> float:
    width, height = source.size
    left, top, right, bottom = target_box
    boxes = [
        (0, 0, width, top),
        (0, bottom, width, height),
        (0, top, left, bottom),
        (right, top, width, bottom),
    ]
    weighted_diff = 0.0
    total_area = 0
    for box in boxes:
        area = max(0, box[2] - box[0]) * max(0, box[3] - box[1])
        if area == 0:
            continue
        weighted_diff += _mean_abs_diff(source, output, box) * area
        total_area += area
    return weighted_diff / total_area if total_area else 0.0
