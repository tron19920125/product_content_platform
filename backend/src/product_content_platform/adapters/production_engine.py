from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageOps, ImageStat

from product_content_platform.application.production_ports import BaseImageGenerator, ProducedCandidate
from product_content_platform.domain import (
    Candidate,
    PageItem,
    ProductProfile,
    Project,
    PromptVersion,
    Recipe,
    validate_image_quality,
    validate_image_size,
)
from product_content_platform.quality.text_review import extract_numbers


class LocalProductionEngine:
    """Deep production module: prompt binding, image creation, composition, QA, repair and ranking."""

    _LAYOUT_SPECS: dict[str, dict[str, Any]] = {
        "hero-center": {
            "text_box": (.09, .07, .91, .29),
            "product_box": (.20, .32, .80, .94),
            "product_anchor_box": (.24, .34, .76, .92),
            "instruction": "顶部 7%-29% 保持纯净低细节留白；商品主体完整居中放在下方 32%-94%，四周保留边距",
        },
        "split-left": {
            "text_box": (.07, .11, .43, .82),
            "product_box": (.48, .16, .94, .94),
            "product_anchor_box": (.52, .20, .92, .92),
            "instruction": "左侧 7%-43% 保持纯净低细节留白；商品主体完整放在右侧 48%-94%，不要进入左侧留白区",
        },
        "split-right": {
            "text_box": (.57, .11, .93, .82),
            "product_box": (.06, .16, .52, .94),
            "product_anchor_box": (.08, .20, .48, .92),
            "instruction": "右侧 57%-93% 保持纯净低细节留白；商品主体完整放在左侧 6%-52%，不要进入右侧留白区",
        },
        "scene-overlay": {
            "text_box": (.07, .08, .44, .28),
            "product_box": (.14, .30, .94, .95),
            "product_anchor_box": (.47, .30, .94, .94),
            "instruction": "左上 7%-44%、顶部 8%-28% 保持安静低对比留白；商品主机的视觉重心放在右下 47%-94%、30%-94%，开门等延展结构可进入 14%-47% 的左下区域，但不得进入左上文字留白区，完整商品保持在画布内",
        },
        "data-grid": {
            "text_box": (.07, .08, .93, .34),
            "product_box": (.20, .38, .80, .94),
            "product_anchor_box": (.24, .40, .76, .92),
            "instruction": "顶部 7%-93%、8%-34% 保持纯净低细节留白；商品主体完整放在下方中央 20%-80%、38%-94%",
        },
    }

    def __init__(
        self,
        root: Path,
        generator: BaseImageGenerator,
        quality_toolkit: Any | None = None,
        template_resolver: Callable[[str], dict[str, Any]] | None = None,
    ) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._generator = generator
        self._quality_toolkit = quality_toolkit
        self._template_resolver = template_resolver
        self._font_path = self._find_font()

    def execute(
        self,
        *,
        project: Project,
        page: PageItem,
        recipe: Recipe,
        prompt_version: PromptVersion,
        reference_paths: list[Path],
    ) -> list[ProducedCandidate]:
        template = self._layout_spec(page.template_id)
        reference_strategy = str(recipe.model_params.get("reference_strategy") or "model_edit")
        max_auto_regenerations = max(0, min(1, int(recipe.model_params.get("max_auto_regenerations", 0))))
        generation_prompt = self._bind_generation_prompt(
            prompt_version.body, project.profile, page, reference_strategy=reference_strategy,
        )
        review_prompt = self._content_review_prompt(project.profile, page)
        review_plan = self._build_review_plan(
            project.profile, page, reference_paths, reference_strategy=reference_strategy,
        )
        generation_size = str(template.get("size") or recipe.model_params.get("size") or "2048x2048")
        validate_image_size(generation_size)
        generation_quality = validate_image_quality(str(recipe.model_params.get("quality") or "high"))
        run_root = self._root / project.id / page.id / str(uuid4())
        produced: list[dict[str, Any]] = []
        for index in range(1, max(1, min(3, recipe.candidate_count)) + 1):
            candidate_root = run_root / f"candidate_{index}"
            base_path = candidate_root / "base.png"
            text_path = candidate_root / "text_layer.png"
            composed_path = candidate_root / "composed.png"
            generator_meta = self._generator.generate(
                prompt=generation_prompt,
                profile=project.profile,
                reference_paths=reference_paths,
                output_path=base_path,
                variant=index,
                size=generation_size,
                quality=generation_quality,
                layout=template,
                reference_strategy=reference_strategy,
            )
            with Image.open(base_path) as generated_image:
                canvas_size = generated_image.size
                allowed_product_bbox = self._product_box(page.template_id, *canvas_size)
                product_anchor_bbox = self._product_anchor_box(page.template_id, *canvas_size)
                product_bbox = tuple(generator_meta.get("product_bbox") or product_anchor_bbox)
            generator_meta["layout"] = {
                "template_id": page.template_id,
                "reserved_text_box": list(self._text_box(page.template_id, *canvas_size)),
                "product_anchor_box": list(product_anchor_bbox),
                "allowed_product_extent_box": list(allowed_product_bbox),
            }
            compose_meta = self._compose(
                base_path=base_path,
                text_path=text_path,
                output_path=composed_path,
                page=page,
                product_bbox=product_bbox,
            )
            qa = self._inspect(
                project.profile, page, reference_paths, generator_meta, compose_meta,
                index, base_path, composed_path, review_prompt, review_plan,
            )
            repair_prompt = ""
            regeneration_fixes = "；".join(
                issue["message"] for issue in qa["issues"] if issue.get("repair") == "regenerate"
            )
            if self._quality_toolkit and regeneration_fixes:
                repair_prompt = self._quality_toolkit.repair_prompt(
                    generation_prompt, regeneration_fixes, "", ""
                )
            repair_history: list[dict[str, Any]] = []
            requires_regeneration = any(issue.get("repair") == "regenerate" for issue in qa["issues"])
            if requires_regeneration and repair_prompt and max_auto_regenerations > 0:
                before_base = candidate_root / "base_before_repair.png"
                before_text = candidate_root / "text_layer_before_repair.png"
                before_composed = candidate_root / "composed_before_repair.png"
                base_path.replace(before_base)
                text_path.replace(before_text)
                composed_path.replace(before_composed)
                repair_history.append({
                    "attempt": 1,
                    "prompt": repair_prompt,
                    "reason": qa["suggested_fix"],
                    "before": {
                        "base_path": self._relative(before_base),
                        "text_layer_path": self._relative(before_text),
                        "composed_path": self._relative(before_composed),
                    },
                })
                generator_meta = self._generator.generate(
                    prompt=repair_prompt,
                    profile=project.profile,
                    reference_paths=reference_paths,
                    output_path=base_path,
                    variant=index,
                    size=generation_size,
                    quality=generation_quality,
                    layout=template,
                    reference_strategy=reference_strategy,
                )
                with Image.open(base_path) as generated_image:
                    canvas_size = generated_image.size
                    allowed_product_bbox = self._product_box(page.template_id, *canvas_size)
                    product_anchor_bbox = self._product_anchor_box(page.template_id, *canvas_size)
                    product_bbox = tuple(generator_meta.get("product_bbox") or product_anchor_bbox)
                generator_meta["layout"] = {
                    "template_id": page.template_id,
                    "reserved_text_box": list(self._text_box(page.template_id, *canvas_size)),
                    "product_anchor_box": list(product_anchor_bbox),
                    "allowed_product_extent_box": list(allowed_product_bbox),
                }
                compose_meta = self._compose(
                    base_path=base_path,
                    text_path=text_path,
                    output_path=composed_path,
                    page=page,
                    product_bbox=product_bbox,
                )
                qa = self._inspect(
                    project.profile, page, reference_paths, generator_meta, compose_meta,
                    index, base_path, composed_path, review_prompt, review_plan,
                )
            produced.append(
                {
                    "candidate_index": index,
                    "base_path": self._relative(base_path),
                    "text_layer_path": self._relative(text_path),
                    "composed_path": self._relative(composed_path),
                    "prompt": generation_prompt,
                    "score": qa["score"],
                    "qa_status": qa["status"],
                    "issues": tuple(qa["issues"]),
                    "evidence": qa["evidence"],
                    "suggested_fix": qa["suggested_fix"],
                    "repair_applied": bool(compose_meta["repair_applied"] or repair_history),
                    "metadata": {
                        "generator": generator_meta,
                        "composition": compose_meta,
                        "recipe_id": recipe.id,
                        "prompt_version_id": prompt_version.id,
                        "model": recipe.model,
                        "model_params": recipe.model_params,
                        "effective_generation": {
                            "size": generation_size,
                            "quality": generation_quality,
                            "template_id": page.template_id,
                            "reference_strategy": reference_strategy,
                            "max_auto_regenerations": max_auto_regenerations,
                        },
                        "review_plan": review_plan,
                        "content_review_prompt": review_prompt,
                        "repair_prompt": repair_prompt,
                        "repair_history": repair_history,
                    },
                }
            )

        if self._quality_toolkit:
            ranked = self._quality_toolkit.rank(produced)
            for item in produced:
                result = ranked[item["candidate_index"]]
                item["score"] = int(result["score"]["overall"])
                item["metadata"]["score_breakdown"] = result["score"]["breakdown"]
                item["rank"] = int(result["rank"])
        else:
            ordered = sorted(produced, key=lambda item: (item["score"], -item["candidate_index"]), reverse=True)
            ranks = {item["candidate_index"]: rank for rank, item in enumerate(ordered, start=1)}
            for item in produced:
                item["rank"] = ranks[item["candidate_index"]]
        return [ProducedCandidate(**item) for item in produced]

    def recompose(
        self,
        *,
        project: Project,
        page: PageItem,
        recipe: Recipe,
        prompt_version: PromptVersion,
        source_candidate: Candidate,
        reference_paths: list[Path],
    ) -> ProducedCandidate:
        reference_strategy = str(recipe.model_params.get("reference_strategy") or "model_edit")
        generation_prompt = self._bind_generation_prompt(
            prompt_version.body, project.profile, page, reference_strategy=reference_strategy,
        )
        review_prompt = self._content_review_prompt(project.profile, page)
        review_plan = self._build_review_plan(
            project.profile, page, reference_paths, reference_strategy=reference_strategy,
        )
        candidate_root = self._root / project.id / page.id / str(uuid4()) / "recompose"
        text_path = candidate_root / "text_layer.png"
        composed_path = candidate_root / "composed.png"
        base_path = self.resolve(source_candidate.base_path)
        generator_meta = dict(source_candidate.metadata.get("generator") or {})
        with Image.open(base_path) as base_image:
            product_bbox = tuple(
                generator_meta.get("product_bbox")
                or self._product_anchor_box(page.template_id, *base_image.size)
            )
        compose_meta = self._compose(
            base_path=base_path,
            text_path=text_path,
            output_path=composed_path,
            page=page,
            product_bbox=product_bbox,
        )
        qa = self._inspect(
            project.profile, page, reference_paths, generator_meta, compose_meta,
            1, base_path, composed_path, review_prompt, review_plan,
        )
        row: dict[str, Any] = {
            "candidate_index": 1,
            "base_path": source_candidate.base_path,
            "text_layer_path": self._relative(text_path),
            "composed_path": self._relative(composed_path),
            "prompt": generation_prompt,
            "score": qa["score"],
            "rank": 1,
            "qa_status": qa["status"],
            "issues": tuple(qa["issues"]),
            "evidence": qa["evidence"],
            "suggested_fix": qa["suggested_fix"],
            "repair_applied": bool(compose_meta["repair_applied"]),
            "metadata": {
                "generator": generator_meta,
                "composition": compose_meta,
                "recipe_id": recipe.id,
                "prompt_version_id": prompt_version.id,
                "model": recipe.model,
                "model_params": recipe.model_params,
                "recomposed_from": source_candidate.id,
                "review_plan": review_plan,
                "content_review_prompt": review_prompt,
                "repair_prompt": "",
            },
        }
        if self._quality_toolkit:
            ranked = self._quality_toolkit.rank([row])[1]
            row["score"] = int(ranked["score"]["overall"])
            row["metadata"]["score_breakdown"] = ranked["score"]["breakdown"]
        return ProducedCandidate(**row)

    def resolve(self, relative_path: str) -> Path:
        target = (self._root / relative_path).resolve()
        if self._root not in target.parents:
            raise ValueError("生产结果路径超出受控目录")
        return target

    def _compose(
        self,
        *,
        base_path: Path,
        text_path: Path,
        output_path: Path,
        page: PageItem,
        product_bbox: tuple[int, int, int, int],
    ) -> dict[str, Any]:
        base = Image.open(base_path).convert("RGBA")
        width, height = base.size
        layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        safe_area = (int(width * .065), int(height * .055), int(width * .935), int(height * .945))
        text_box = self._text_box(page.template_id, width, height)
        short_edge = min(width, height)
        requested_title_size = round(short_edge * {1: .065, 2: .058, 3: .052, 4: .047, 5: .042}.get(page.heading_level, .058))
        requested_body_size = round(short_edge * .029)
        title_size = requested_title_size
        body_size = requested_body_size
        title_min = max(24, round(short_edge * .033))
        body_min = max(18, round(short_edge * .018))
        title_spacing = max(8, round(short_edge * .006))
        body_spacing = max(6, round(short_edge * .0045))
        title_body_gap = max(18, round(short_edge * .018))
        text_width = text_box[2] - text_box[0]
        text_height = text_box[3] - text_box[1]
        while True:
            title_lines, title_font = self._fit_lines(
                draw, page.title, text_width, title_size, title_min, 2
            )
            body_lines, body_font = self._fit_lines(
                draw, page.body, text_width, body_size, body_min, 4
            )
            title_preview = "\n".join(title_lines)
            body_preview = "\n".join(body_lines)
            title_preview_bbox = draw.multiline_textbbox(
                (0, 0), title_preview, font=title_font, spacing=title_spacing
            )
            body_preview_bbox = draw.multiline_textbbox(
                (0, 0), body_preview, font=body_font, spacing=body_spacing
            )
            block_height = (
                title_preview_bbox[3] - title_preview_bbox[1]
                + title_body_gap
                + body_preview_bbox[3] - body_preview_bbox[1]
            )
            if block_height <= text_height or (title_font.size <= title_min and body_font.size <= body_min):
                break
            title_size = max(title_min, title_font.size - 2)
            body_size = max(body_min, body_font.size - 2)
        repair_applied = (
            title_font.size < requested_title_size or body_font.size < requested_body_size
        )
        x, y = text_box[0], text_box[1]
        title_color, body_color, color_name = self._text_colors(base, text_box)
        title_text = "\n".join(title_lines)
        draw.multiline_text((x, y), title_text, font=title_font, fill=title_color, spacing=title_spacing)
        title_bbox = draw.multiline_textbbox((x, y), title_text, font=title_font, spacing=title_spacing)
        body_y = title_bbox[3] + title_body_gap
        body_text = "\n".join(body_lines)
        draw.multiline_text((x, body_y), body_text, font=body_font, fill=body_color, spacing=body_spacing)
        body_bbox = draw.multiline_textbbox((x, body_y), body_text, font=body_font, spacing=body_spacing)
        rendered_bbox = (
            min(title_bbox[0], body_bbox[0]), min(title_bbox[1], body_bbox[1]),
            max(title_bbox[2], body_bbox[2]), max(title_bbox[3], body_bbox[3]),
        )
        text_path.parent.mkdir(parents=True, exist_ok=True)
        layer.save(text_path, format="PNG")
        Image.alpha_composite(base, layer).convert("RGB").save(output_path, format="PNG")
        return {
            "canvas": [width, height],
            "safe_area": list(safe_area),
            "text_box": list(text_box),
            "rendered_text_bbox": list(rendered_bbox),
            "product_bbox": list(product_bbox),
            "title_font_size": title_font.size,
            "title_lines": title_lines,
            "heading_level": page.heading_level,
            "body_font_size": body_font.size,
            "body_lines": body_lines,
            "font": self._font_path.name if self._font_path else "PillowDefault",
            "text_color": color_name,
            "background_luminance": round(self._region_luminance(base, text_box), 2),
            "repair_applied": repair_applied,
        }

    def _inspect(
        self,
        profile: ProductProfile,
        page: PageItem,
        reference_paths: list[Path],
        generator_meta: dict[str, Any],
        compose_meta: dict[str, Any],
        index: int,
        base_path: Path,
        output_path: Path,
        prompt: str,
        review_plan: dict[str, Any],
    ) -> dict[str, Any]:
        issues: list[dict[str, Any]] = []
        safe = tuple(compose_meta["safe_area"])
        rendered = tuple(compose_meta["rendered_text_bbox"])
        product = tuple(compose_meta["product_bbox"])
        if not self._contains(safe, rendered):
            issues.append(self._issue("template_safe_area", "P0", "文字超出模板安全区", "recompose"))
        overlap = self._overlap_ratio(rendered, product)
        if overlap > .04:
            issues.append(self._issue("subject_text_overlap", "P1", "文字遮挡商品主体", "recompose"))
        expected_text = f"{page.title}\n{page.body}".strip()
        if not page.title.strip():
            issues.append(self._issue("title_missing", "P0", "页面标题为空", "copy"))
        allowed_source = " ".join([
            profile.sku, profile.model, profile.name, *profile.selling_points,
            *(f"{key} {value}" for key, value in profile.parameters.items()),
        ])
        found_numbers = self._numbers(expected_text)
        allowed_numbers = self._numbers(allowed_source)
        copy_number_allowlist = extract_numbers(allowed_source)
        invented = sorted(set(found_numbers) - set(allowed_numbers))
        if invented:
            issues.append(self._issue("product_fact_mismatch", "P0", f"出现未确认数字：{', '.join(invented)}", "copy"))
        if not reference_paths:
            issues.append(self._issue("reference_missing", "P2", "缺少商品参考图，商品外观需人工确认", "manual"))
        if profile.brand_requirements and "禁用" in profile.brand_requirements:
            forbidden = [part.strip() for part in re.split(r"[：:，,；;]", profile.brand_requirements)[1:] if part.strip()]
            hit = [word for word in forbidden if word in expected_text]
            if hit:
                issues.append(self._issue("brand_forbidden_term", "P1", f"命中品牌禁用项：{', '.join(hit)}", "copy"))

        text_review: dict[str, Any] = {}
        visual_review: dict[str, Any] = {}
        llm_review: dict[str, Any] = {}
        ocr_evidence: dict[str, Any] = {
            "provider": "text-layer",
            "recognized_text": expected_text,
            "bbox": list(rendered),
        }
        base_text_evidence: dict[str, Any] = {}
        reference_similarity: float | None = None
        if self._quality_toolkit:
            canvas_width, canvas_height = compose_meta["canvas"]
            bbox = (
                rendered[0] / canvas_width, rendered[1] / canvas_height,
                rendered[2] / canvas_width, rendered[3] / canvas_height,
            )
            reserved = compose_meta["text_box"]
            reserved_bbox = (
                reserved[0] / canvas_width, reserved[1] / canvas_height,
                reserved[2] / canvas_width, reserved[3] / canvas_height,
            )
            if hasattr(self._quality_toolkit, "inspect_reserved_area"):
                base_text_evidence = self._quality_toolkit.inspect_reserved_area(base_path, reserved_bbox)
                unexpected_lines = base_text_evidence.get("unexpected_lines", [])
                if unexpected_lines:
                    sample = "、".join(str(row.get("text", "")) for row in unexpected_lines[:3])
                    issues.append(self._issue(
                        "base_image_text_in_reserved_area",
                        "P1",
                        f"底图预留区出现模型生成文字：{sample}",
                        "regenerate",
                    ))
            if reference_paths:
                bbox_source = str(generator_meta.get("product_bbox_source") or "")
                similarity_box = generator_meta.get("product_bbox")
                if bbox_source == "layered_reference":
                    reference_similarity = 1.0
                elif similarity_box:
                    reference_similarity = self._reference_similarity(
                        reference_paths[0], base_path, tuple(similarity_box)
                    )
                if reference_similarity is not None and reference_similarity < .55:
                    issues.append(self._issue(
                        "product_reference_low", "P1",
                        f"商品外观与参考图一致性偏低（{reference_similarity:.2f}）",
                        "regenerate",
                    ))
                product_box = compose_meta["product_bbox"]
                target_region = (
                    product_box[0] / canvas_width, product_box[1] / canvas_height,
                    product_box[2] / canvas_width, product_box[3] / canvas_height,
                )
                visual_review = self._quality_toolkit.visual_evidence(reference_paths[0], output_path, target_region)

            if hasattr(self._quality_toolkit, "review_candidate"):
                composition_provenance = {
                    "post_composed": True,
                    "renderer": "Pillow",
                    "base_image_stored_separately": True,
                    "text_layer_stored_separately": True,
                    "base_image_path": self._relative(base_path),
                    "text_layer_path": self._relative(output_path.parent / "text_layer.png"),
                    "composed_image_path": self._relative(output_path),
                    "authoritative_title": page.title,
                    "authoritative_body": page.body,
                    "product_layer_file": generator_meta.get("product_layer_file", ""),
                    "reference_strategy": generator_meta.get("reference_strategy", ""),
                }
                combined_review = self._quality_toolkit.review_candidate(
                    output_path=output_path,
                    reference_path=reference_paths[0] if reference_paths else None,
                    prompt=prompt,
                    review_plan=review_plan,
                    visual_review=visual_review,
                    generation={**generator_meta, "composition_provenance": composition_provenance},
                    title=page.title,
                    body=page.body,
                    bbox=bbox,
                    number_allowlist=copy_number_allowlist,
                )
                text_review = combined_review.get("text_review", {})
                llm_review = combined_review.get("llm_review", {})
                ocr_lines = combined_review.get("ocr_lines", [])
                if ocr_lines:
                    ocr_evidence = {
                        "provider": combined_review.get("provider", "ocr"),
                        "recognized_text": "\n".join(str(line.get("text", "")) for line in ocr_lines),
                        "lines": ocr_lines,
                    }
            else:
                text_review = self._quality_toolkit.review_known_text(
                    title=page.title, body=page.body, bbox=bbox, number_allowlist=copy_number_allowlist
                )

            for text_issue in text_review.get("issues", []):
                issues.append(self._issue(
                    text_issue.get("code", "ocr_text_issue"),
                    text_issue.get("severity", "P1"),
                    text_issue.get("message", "文字审查未通过"),
                    "recompose",
                ))
            for review_issue in llm_review.get("issues", []):
                category = review_issue.get("code", "multimodal_review")
                issues.append(self._issue(
                    f"llm_{category}",
                    review_issue.get("severity", "P2"),
                    review_issue.get("message", "多模态审查需人工确认"),
                    self._llm_repair_type(category),
                ))

        severities = {item["severity"] for item in issues}
        status = "fail" if "P0" in severities else "review" if issues else "pass"
        base_score = 97 if status == "pass" else 84 if status == "review" else 52
        score = max(0, min(100, base_score - max(0, index - 1) * 2 - (4 if compose_meta["repair_applied"] else 0)))
        return {
            "status": status,
            "score": score,
            "issues": issues,
            "suggested_fix": "；".join(item["message"] for item in issues if item["repair"] != "manual"),
            "evidence": {
                "ocr": ocr_evidence,
                "base_image_text": base_text_evidence,
                "layout": {"canvas": compose_meta["canvas"], "safe_area": list(safe), "text_bbox": list(rendered), "subject_bbox": list(product), "overlap_ratio": round(overlap, 4)},
                "composition_provenance": {
                    "post_composed": True,
                    "renderer": "Pillow",
                    "base_image_path": self._relative(base_path),
                    "text_layer_path": self._relative(output_path.parent / "text_layer.png"),
                    "composed_image_path": self._relative(output_path),
                    "authoritative_title": page.title,
                    "authoritative_body": page.body,
                },
                "product_facts": {
                    "found_numbers": found_numbers,
                    "allowed_numbers": allowed_numbers,
                    "copy_number_allowlist": copy_number_allowlist,
                    "invented_numbers": invented,
                },
                "reference_consistency": {"reference_count": len(reference_paths), "generator_source": generator_meta.get("source_reference", ""), "product_similarity": reference_similarity},
                "brand_and_multi_page": {"font": compose_meta["font"], "text_color": compose_meta["text_color"], "template_id": page.template_id},
                "text_review": text_review,
                "visual_review": visual_review,
                "multimodal_review": llm_review,
            },
        }

    def _build_review_plan(
        self,
        profile: ProductProfile,
        page: PageItem,
        reference_paths: list[Path],
        *,
        reference_strategy: str = "model_edit",
    ) -> dict[str, Any]:
        """Build production QA from structured facts instead of re-interpreting copy with an LLM."""
        layout_instruction = self._layout_spec(page.template_id)["instruction"]
        reference_requirement = (
            "商品外观、颜色、结构、品牌标识位置和物理控制面板应与参考图一致"
            if reference_paths
            else "商品外观需要人工确认，因为没有提供参考图"
        )
        return {
            "mode": "generate",
            "source": "production-structured",
            "summary": f"审查{profile.name}的电商页面视觉、布局与参考商品一致性",
            "edit_target": "审查生图底图与后期排字合成后的候选图",
            # Exact copy is deliberately not delegated to the LLM. Azure OCR plus
            # the saved text layer perform that deterministic check.
            "must_appear": [
                f"构图意图：{layout_instruction}。商品锚点是视觉重心建议，不是要求所有开门、把手等延展结构都落入锚点矩形的硬边界",
                reference_requirement,
            ],
            "must_not_appear": [
                "商品主体、门体、机身边缘或关键结构不得被裁切或被后期文字遮挡",
                "预留文字区不得出现由生图模型生成的标题、正文、占位符、水印或装饰性伪文字",
                "商品及其开门、把手等延展结构不得进入左上文字留白区",
            ],
            "must_preserve": [
                "参考商品本体已有的品牌标识和物理面板信息允许保留，并只按参考一致性检查；"
                "它们不是后期营销文案，也不参与营销文案数字白名单检查",
            ],
            "review_checks": [
                "检查商品比例、透视、门体、控制面板和关键结构是否自然稳定",
                "检查整体清晰度、材质、光影、留白和电商视觉质量",
                "若商品面板相对参考图出现明显新增乱码或损坏，只合并报告一次参考一致性问题",
            ],
            "target_hint": layout_instruction,
            "target_region": self._layout_spec(page.template_id).get("product_anchor_box")
            or self._layout_spec(page.template_id)["product_box"],
            "allowed_product_extent_region": self._layout_spec(page.template_id)["product_box"],
            "authoritative_copy": {
                "title": page.title,
                "body": page.body,
                "serialization": json.dumps(
                    {"title": page.title, "body": page.body}, ensure_ascii=False
                ),
                "policy": "逐字匹配原文，不添加或删除任何标点；由 OCR 和独立文字层确定性校验",
            },
            "composition_evidence": {
                "post_composed": True,
                "base_and_text_layer_are_separate_files": True,
                "copy_review_owner": "deterministic_ocr",
                "product_composition_strategy": reference_strategy,
                "reference_product_layer_is_exact_source": reference_strategy == "layered_product",
            },
        }

    def _fit_lines(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        max_width: int,
        start_size: int,
        min_size: int,
        max_lines: int,
    ) -> tuple[list[str], ImageFont.FreeTypeFont | ImageFont.ImageFont]:
        normalized = text.strip() or " "
        for size in range(start_size, min_size - 1, -2):
            font = self._font(size)
            lines = self._wrap(draw, normalized, font, max_width)
            punctuation_lines = self._title_punctuation_lines(normalized) if max_lines == 2 else None
            if (
                len(lines) > 1
                and punctuation_lines
                and all(draw.textlength(line, font=font) <= max_width for line in punctuation_lines)
            ):
                return punctuation_lines, font
            if len(lines) <= max_lines and not self._has_orphan_line(lines):
                return lines, font
        font = self._font(min_size)
        return self._wrap(draw, normalized, font, max_width), font

    @staticmethod
    def _has_orphan_line(lines: list[str]) -> bool:
        """Avoid a visually weak final line containing only one or two glyphs."""
        if len(lines) < 2:
            return False
        visible = [line.strip() for line in lines if line.strip()]
        if len(visible) < 2:
            return False
        total_length = sum(len(line) for line in visible)
        return len(visible[-1]) <= 2 and total_length >= 6

    @staticmethod
    def _title_punctuation_lines(text: str) -> list[str] | None:
        for mark in ("，", ",", "：", ":", "；", ";"):
            if text.count(mark) != 1:
                continue
            before, after = text.split(mark, 1)
            if before.strip() and after.strip():
                return [before.strip() + mark, after.strip()]
        return None

    @staticmethod
    def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
        lines: list[str] = []
        current = ""
        for char in text:
            if char == "\n":
                lines.append(current)
                current = ""
                continue
            candidate = current + char
            if current and draw.textlength(candidate, font=font) > max_width:
                lines.append(current)
                current = char
            else:
                current = candidate
        if current or not lines:
            lines.append(current)
        return lines

    def _font(self, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        return ImageFont.truetype(str(self._font_path), size) if self._font_path else ImageFont.load_default(size=size)

    @staticmethod
    def _region_luminance(image: Image.Image, box: tuple[int, int, int, int]) -> float:
        region = ImageOps.grayscale(image.crop(box))
        return float(ImageStat.Stat(region).mean[0])

    @classmethod
    def _text_colors(
        cls, image: Image.Image, box: tuple[int, int, int, int]
    ) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int], str]:
        if cls._region_luminance(image, box) >= 145:
            return (24, 31, 28, 255), (55, 65, 60, 255), "#181F1C"
        return (250, 253, 251, 255), (221, 231, 225, 255), "#FAFDFB"

    @staticmethod
    def _find_font() -> Path | None:
        configured = os.environ.get("PCP_FONT_PATH", "").strip()
        windows_fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        candidates = [Path(configured)] if configured else []
        candidates.extend(
            (
                windows_fonts / "msyh.ttc",
                windows_fonts / "msyhbd.ttc",
                windows_fonts / "Deng.ttf",
                windows_fonts / "simhei.ttf",
                windows_fonts / "simsun.ttc",
                Path("/System/Library/Fonts/PingFang.ttc"),
                Path("/System/Library/Fonts/STHeiti Light.ttc"),
                Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
                Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
                Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            )
        )
        for path in candidates:
            if path.exists():
                return path
        return None

    def _layout_spec(self, template_id: str) -> dict[str, Any]:
        if self._template_resolver is not None:
            template = self._template_resolver(template_id)
            return {
                **template,
                "instruction": template.get("composition_instruction") or template.get("instruction") or "",
            }
        return self._LAYOUT_SPECS.get(template_id, self._LAYOUT_SPECS["split-left"])

    def _text_box(self, template_id: str, width: int, height: int) -> tuple[int, int, int, int]:
        x1, y1, x2, y2 = self._layout_spec(template_id)["text_box"]
        return int(width * x1), int(height * y1), int(width * x2), int(height * y2)

    def _product_box(self, template_id: str, width: int, height: int) -> tuple[int, int, int, int]:
        x1, y1, x2, y2 = self._layout_spec(template_id)["product_box"]
        return int(width * x1), int(height * y1), int(width * x2), int(height * y2)

    def _product_anchor_box(self, template_id: str, width: int, height: int) -> tuple[int, int, int, int]:
        layout = self._layout_spec(template_id)
        x1, y1, x2, y2 = layout.get("product_anchor_box") or layout["product_box"]
        return int(width * x1), int(height * y1), int(width * x2), int(height * y2)

    @staticmethod
    def _contains(outer: tuple[int, ...], inner: tuple[int, ...]) -> bool:
        return outer[0] <= inner[0] and outer[1] <= inner[1] and inner[2] <= outer[2] and inner[3] <= outer[3]

    @staticmethod
    def _overlap_ratio(first: tuple[int, ...], second: tuple[int, ...]) -> float:
        width = max(0, min(first[2], second[2]) - max(first[0], second[0]))
        height = max(0, min(first[3], second[3]) - max(first[1], second[1]))
        area = max(1, (first[2] - first[0]) * (first[3] - first[1]))
        return (width * height) / area

    @staticmethod
    def _numbers(value: str) -> list[str]:
        return re.findall(r"\d+(?:\.\d+)?", value)

    @staticmethod
    def _reference_similarity(reference_path: Path, base_path: Path, product_bbox: tuple[int, ...]) -> float:
        reference = Image.open(reference_path).convert("RGB")
        base = Image.open(base_path).convert("RGB")
        left, top, right, bottom = product_bbox
        left, top = max(0, left), max(0, top)
        right, bottom = min(base.width, right), min(base.height, bottom)
        if right <= left or bottom <= top:
            return 0.0
        product = base.crop((left, top, right, bottom))
        normalized_reference = ImageOps.fit(reference, product.size, method=Image.Resampling.BOX)
        normalized_reference = ImageOps.grayscale(normalized_reference).resize((128, 128), Image.Resampling.BOX)
        normalized_product = ImageOps.grayscale(product).resize((128, 128), Image.Resampling.BOX)
        difference = ImageStat.Stat(ImageChops.difference(normalized_reference, normalized_product)).mean[0]
        return max(0.0, min(1.0, 1.0 - difference / 255.0))

    @staticmethod
    def _issue(code: str, severity: str, message: str, repair: str) -> dict[str, Any]:
        return {"code": code, "severity": severity, "message": message, "repair": repair}

    @staticmethod
    def _llm_repair_type(category: str) -> str:
        if category in {"text_accuracy", "layout_position"}:
            return "recompose"
        if category in {"prompt_following", "reference_consistency", "visual_quality"}:
            return "regenerate"
        return "manual"

    def _bind_generation_prompt(
        self,
        body: str,
        profile: ProductProfile,
        page: PageItem,
        *,
        reference_strategy: str = "model_edit",
    ) -> str:
        template = self._layout_spec(page.template_id)
        layout_instruction = template["instruction"]
        values = {
            "product_name": profile.name,
            "sku": profile.sku,
            "model": profile.model,
            "category": profile.category,
            "selling_points": "；".join(profile.selling_points),
            "page_title": "预留标题区域，不生成标题文字",
            "page_body": "预留正文区域，不生成正文文字",
            "visual_goal": page.visual_goal,
            "template_id": page.template_id,
            "composition_instruction": layout_instruction,
            "scene_prompt_hint": str(template.get("scene_prompt_hint") or ""),
        }
        result = body
        for key, value in values.items():
            result = result.replace("{{" + key + "}}", value)
        for copy in (page.title.strip(), page.body.strip()):
            if copy:
                result = result.replace(copy, "")
        product_guardrail = (
            "最高优先级：商品将由系统在生图后从用户参考图中原样抠出并合成。你只生成空置场景底图，"
            "不要生成、绘制、复制或暗示任何商品、家电、机器、展台占位块、商品轮廓或商品文字；"
            "在模板商品允许区域保留连续、自然、可承接商品层的墙面和地面，并保持光向一致。"
            if reference_strategy == "layered_product"
            else "商品必须完整出现在画面内，不得裁切机身、门体或关键结构。"
        )
        guardrails = (
            f"构图约束：{layout_instruction}。"
            "预留文字区域必须保持背景简洁、低细节、低对比，不放置商品主体或关键物体。"
            f"{product_guardrail}"
            "这是纯视觉底图：预留文字区域内严禁出现标题、正文、标语、字母、数字、Logo、水印、"
            "文本框、占位符、横线或类似字符的图形；画面其他区域也不得新增文字。"
            "参考图中商品本体已有的品牌标识和物理面板信息应保持原样；不要把留白区画成边框。"
        )
        return f"{result.strip()}\n\n{guardrails}"

    def _content_review_prompt(self, profile: ProductProfile, page: PageItem) -> str:
        layout_instruction = self._layout_spec(page.template_id)["instruction"]
        exact_copy = json.dumps({"title": page.title, "body": page.body}, ensure_ascii=False)
        return (
            f"为{profile.name}制作电商详情页。最终文案以此 JSON 为唯一依据：{exact_copy}。"
            "JSON 字符串结束后的句号只是说明文字的分隔符，不属于文案；不得推断、补充或删除标点。"
            f"视觉目标：{page.visual_goal}。模板：{page.template_id}。构图要求：{layout_instruction}。"
            "底图不得自带文字；标题和正文必须只由后期文字层放入预留区域。"
        )

    def _relative(self, path: Path) -> str:
        return str(path.resolve().relative_to(self._root))
