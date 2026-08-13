from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps, ImageStat

from product_content_platform.application.production_ports import BaseImageGenerator, ProducedCandidate
from product_content_platform.domain import (
    Candidate,
    PageItem,
    ProductProfile,
    Project,
    PromptVersion,
    Recipe,
    TextDocument,
    TextLayer,
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
        font_resolver: Callable[[str], Path | None] | None = None,
    ) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._generator = generator
        self._quality_toolkit = quality_toolkit
        self._template_resolver = template_resolver
        self._font_resolver = font_resolver
        self._font_paths = self._find_fonts()
        self._font_path = self._font_paths["system_sans"]

    def execute(
        self,
        *,
        project: Project,
        page: PageItem,
        recipe: Recipe,
        prompt_version: PromptVersion,
        reference_paths: list[Path],
        progress: Callable[[str, int, dict[str, Any]], None] | None = None,
    ) -> list[ProducedCandidate]:
        def report(stage: str, percent: int, **details: Any) -> None:
            if progress:
                progress(stage, max(0, min(100, percent)), details)

        report("preparing", 5, label="准备 Prompt、模板与参考素材")
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
        total_candidates = max(1, min(3, recipe.candidate_count))
        candidate_span = 88 / total_candidates
        for index in range(1, total_candidates + 1):
            candidate_start = 5 + (index - 1) * candidate_span

            def candidate_percent(fraction: float) -> int:
                return round(candidate_start + candidate_span * fraction)

            candidate_root = run_root / f"candidate_{index}"
            base_path = candidate_root / "base.png"
            text_path = candidate_root / "text_layer.png"
            composed_path = candidate_root / "composed.png"
            report(
                "generating_background", candidate_percent(.08),
                label=(
                    "Azure 正在生成场景底图，随后合成原样商品层"
                    if reference_strategy == "layered_product"
                    else "Azure 正在依据多张参考图生成商品与场景"
                ),
                candidate_index=index, candidate_count=total_candidates,
            )
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
            report(
                "compositing_product", candidate_percent(.58),
                label=(
                    "正在合成原样商品图层"
                    if reference_strategy == "layered_product"
                    else "模型商品与场景已生成，正在校验构图"
                ),
                candidate_index=index, candidate_count=total_candidates,
                image_elapsed_seconds=generator_meta.get("elapsed_seconds"),
            )
            with Image.open(base_path) as generated_image:
                canvas_size = generated_image.size
                allowed_product_bbox = self._product_box(page.template_id, *canvas_size)
                product_anchor_bbox = self._product_anchor_box(page.template_id, *canvas_size)
                product_bbox = tuple(generator_meta.get("product_bbox") or product_anchor_bbox)
            generator_meta["layout"] = {
                "template_id": page.template_id,
                "template_key": template.get("template_key") or page.template_id,
                "template_version": int(template.get("version", 1)),
                "library_id": template.get("library_id") or "",
                "canvas_size": template.get("size") or generation_size,
                "reserved_text_box": list(self._text_box(page.template_id, *canvas_size)),
                "reserved_title_box": list(self._scaled_box(template.get("title_box") or template["text_box"], *canvas_size)),
                "reserved_body_box": list(self._scaled_box(template.get("body_box") or template["text_box"], *canvas_size)),
                "product_anchor_box": list(product_anchor_bbox),
                "allowed_product_extent_box": list(allowed_product_bbox),
            }
            report(
                "compositing_text", candidate_percent(.66),
                label="执行确定性文字排版",
                candidate_index=index, candidate_count=total_candidates,
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
                index, base_path, composed_path, review_prompt, review_plan,
                progress=lambda stage, details: report(
                    stage,
                    candidate_percent({
                        "checking_base_text": .72,
                        "checking_reference": .78,
                        "ocr_output": .82,
                        "ocr_reference": .86,
                        "llm_review": .90,
                    }.get(stage, .74)),
                    candidate_index=index,
                    candidate_count=total_candidates,
                    **details,
                ),
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
                    "template_key": template.get("template_key") or page.template_id,
                    "template_version": int(template.get("version", 1)),
                    "library_id": template.get("library_id") or "",
                    "canvas_size": template.get("size") or generation_size,
                    "reserved_text_box": list(self._text_box(page.template_id, *canvas_size)),
                    "reserved_title_box": list(self._scaled_box(template.get("title_box") or template["text_box"], *canvas_size)),
                    "reserved_body_box": list(self._scaled_box(template.get("body_box") or template["text_box"], *canvas_size)),
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
                    progress=lambda stage, details: report(
                        stage, candidate_percent(.92),
                        candidate_index=index, candidate_count=total_candidates,
                        **{**details, "label": "复核自动修复结果"},
                    ),
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
            report(
                "candidate_completed", candidate_percent(.96),
                label=f"候选 {index}/{total_candidates} 已完成",
                candidate_index=index, candidate_count=total_candidates,
            )

        if self._quality_toolkit:
            report("ranking", 96, label="汇总 QA 证据并排序候选")
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
        report("finalizing", 98, label="保存候选、图层和 QA 结果")
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
        typography: dict[str, Any] | None = None,
    ) -> ProducedCandidate:
        reference_strategy = str(recipe.model_params.get("reference_strategy") or "model_edit")
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
            typography=typography,
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
            # Recomposition never calls the image model. Keep the exact prompt
            # that created the reused base instead of rebuilding a hypothetical
            # prompt from the current plan.
            "prompt": source_candidate.prompt,
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
                "effective_generation": dict(
                    source_candidate.metadata.get("effective_generation")
                    or {
                        "size": generator_meta.get("requested_size") or generator_meta.get("actual_size") or "",
                        "quality": generator_meta.get("quality") or "",
                        "template_id": (generator_meta.get("layout") or {}).get("template_id") or page.template_id,
                        "reference_strategy": generator_meta.get("reference_strategy") or reference_strategy,
                        "max_auto_regenerations": int(recipe.model_params.get("max_auto_regenerations", 0)),
                    }
                ),
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

    def suggest_text_document(
        self,
        *,
        candidate: Candidate,
        page: PageItem,
        instruction: str = "",
        current: TextDocument | None = None,
    ) -> TextDocument:
        """Create an editable first-pass layout without changing the base image."""
        if current is None:
            restored = self._restore_candidate_text_document(candidate=candidate, page=page)
            if restored is not None:
                return restored
        template = self._layout_spec(page.template_id)
        slots = list(template.get("text_slots") or [
            {"id": "headline", "name": "标题", "role": "headline", "box": template.get("title_box") or template["text_box"]},
            {"id": "body", "name": "正文", "role": "body", "box": template.get("body_box") or template["text_box"]},
        ])
        current_by_role = {layer.role: layer for layer in (current.layers if current else ())}
        current_by_id = {layer.id: layer for layer in (current.layers if current else ())}
        art_direction = instruction.strip()
        expressive = any(term in art_direction.lower() for term in ("艺术", "潮流", "活力", "年轻", "art", "bold"))
        traditional = any(term in art_direction.lower() for term in ("国风", "书法", "东方", "古典", "chinese"))
        font_family = "ma-shan-zheng" if traditional else ("smiley-sans" if expressive else "noto-sans-sc")
        with Image.open(self.resolve(candidate.base_path)) as base:
            width, height = base.size
            short_edge = min(width, height)
        layers: list[TextLayer] = []
        for index, slot in enumerate(slots):
            role = str(slot.get("role") or "custom")
            existing = current_by_id.get(str(slot.get("id"))) or current_by_role.get(role)
            content = (
                existing.content if existing else
                page.title if role == "headline" else
                page.body if role in {"body", "subheadline"} else ""
            )
            if not content and not slot.get("required"):
                continue
            box = tuple(float(part) for part in slot["box"])
            box_height = max(.02, box[3] - box[1])
            suggested_size = round(min(short_edge * (.072 if role == "headline" else .036), height * box_height * .58))
            defaults = dict(slot.get("default_style") or {})
            layer_value = existing.to_dict() if existing else {}
            layer_value.update({
                "id": str(slot.get("id") or f"text-{index + 1}"),
                "role": role if role in {"headline", "body", "badge", "caption", "custom"} else "custom",
                "name": str(slot.get("name") or "文本框"), "content": content,
                "box": list(box), "z_index": index, "source": "ai",
                "font_family": defaults.get("font_family") or (existing.font_family if existing else font_family),
                "font_weight": defaults.get("font_weight") or (existing.font_weight if existing else (700 if role == "headline" else 400)),
                "font_size": defaults.get("font_size") or (existing.font_size if existing else max(18, suggested_size)),
                "line_height": defaults.get("line_height") or (existing.line_height if existing else (1.12 if role == "headline" else 1.45)),
                "letter_spacing": defaults.get("letter_spacing") if defaults.get("letter_spacing") is not None else (existing.letter_spacing if existing else (2 if role == "headline" else 0)),
            })
            layers.append(TextLayer.from_dict(layer_value))
        slot_ids = {str(slot.get("id")) for slot in slots}
        slot_roles = {str(slot.get("role")) for slot in slots}
        for existing in (current.layers if current else ()):
            if existing.id not in slot_ids:
                layers.append(TextLayer.from_dict({
                    **existing.to_dict(), "z_index": len(layers), "source": "ai",
                }))
        reasoning = "依据模板预留区、画布比例和文案层级完成初排；图片模型生成的底图未被修改。"
        if art_direction:
            reasoning += f" 已结合设计要求：{art_direction}"
        return TextDocument(
            candidate_id=candidate.id, version=(current.version + 1 if current else 1),
            layers=tuple(layers), source="ai", ai_reasoning=reasoning,
        )

    def _restore_candidate_text_document(
        self,
        *,
        candidate: Candidate,
        page: PageItem,
    ) -> TextDocument | None:
        """Restore the editable document from the text that is already baked into composed.png."""
        composition = dict(candidate.metadata.get("composition") or candidate.metadata.get("compose") or {})
        rendered_layers = composition.get("text_layers")
        is_showcase = bool(composition.get("showcase_seed"))
        has_legacy_render = bool(composition.get("canvas") and composition.get("title_font_size"))
        if not isinstance(rendered_layers, list) and not is_showcase and not has_legacy_render:
            return None

        with Image.open(self.resolve(candidate.base_path)) as base:
            width, height = base.size

        def normalized_box(value: Any, fallback: Any) -> list[float]:
            parts = list(value or fallback)
            if len(parts) != 4:
                parts = list(fallback)
            if max(float(part) for part in parts) > 1:
                parts = [parts[0] / width, parts[1] / height, parts[2] / width, parts[3] / height]
            return [min(1, max(0, round(float(part), 6))) for part in parts]

        layers: list[TextLayer] = []
        if isinstance(rendered_layers, list):
            for index, raw in enumerate(rendered_layers):
                if not isinstance(raw, dict):
                    continue
                role = str(raw.get("role") or "custom")
                lines = raw.get("lines")
                content = str(raw.get("content") or ("\n".join(str(line) for line in lines) if isinstance(lines, list) else ""))
                layers.append(TextLayer.from_dict({
                    **raw,
                    "id": str(raw.get("id") or f"text-{index + 1}"),
                    "role": role,
                    "name": str(raw.get("name") or {"headline": "标题", "body": "正文"}.get(role, "文本框")),
                    "content": content,
                    "box": normalized_box(raw.get("box"), [.08, .08, .92, .20]),
                    "font_family": str(raw.get("font_family") or "system_sans"),
                    "font_size": int(raw.get("requested_font_size") or raw.get("font_size") or 64),
                    "z_index": index,
                    "source": "candidate",
                }))
        else:
            template = self._layout_spec(page.template_id)
            short_edge = min(width, height)
            title_size = int(composition.get("title_font_size") or round(short_edge * {
                1: .065, 2: .058, 3: .052, 4: .047, 5: .042,
            }.get(page.heading_level, .058)))
            body_size = int(composition.get("body_font_size") or round(short_edge * .029))
            title_spacing = int(composition.get("title_line_spacing") or max(8, round(short_edge * .006)))
            body_spacing = int(composition.get("body_line_spacing") or max(6, round(short_edge * .0045)))
            font_family = str(composition.get("font_family") or "system_sans")
            align = str(composition.get("text_align") or "left")
            vertical = str(composition.get("vertical_align") or "top")
            title_color = str(composition.get("title_color") or ("#1F3027" if is_showcase else "#181F1C"))
            body_color = str(composition.get("body_color") or ("#42564A" if is_showcase else title_color))
            for index, (role, name, content, box, size, color, spacing) in enumerate((
                ("headline", "标题", page.title, composition.get("title_box") or template.get("title_box") or template["text_box"], title_size, title_color, title_spacing),
                ("body", "正文", page.body, composition.get("body_box") or template.get("body_box") or template["text_box"], body_size, body_color, body_spacing),
            )):
                if not content:
                    continue
                layers.append(TextLayer.from_dict({
                    "id": role, "role": role, "name": name, "content": content,
                    "box": normalized_box(box, [.08, .08, .92, .20]),
                    "font_family": font_family, "font_weight": 400, "font_size": size,
                    "color": color, "text_align": align, "vertical_align": vertical,
                    "line_height": round(1 + spacing / max(size, 1), 3),
                    "letter_spacing": 0, "z_index": index, "source": "candidate",
                }))
        if not layers:
            return None
        return TextDocument(
            candidate_id=candidate.id,
            version=1,
            layers=tuple(layers),
            source="candidate",
            ai_reasoning="已从当前候选图的实际合成记录恢复字体、字号、颜色、位置和对齐方式。",
        )

    def recompose_document(
        self,
        *,
        project: Project,
        page: PageItem,
        recipe: Recipe,
        prompt_version: PromptVersion,
        source_candidate: Candidate,
        text_document: TextDocument,
        reference_paths: list[Path],
        run_qa: bool = False,
    ) -> ProducedCandidate:
        candidate_root = self._root / project.id / page.id / str(uuid4()) / "text-edit"
        text_path = candidate_root / "text_layer.png"
        composed_path = candidate_root / "composed.png"
        base_path = self.resolve(source_candidate.base_path)
        generator_meta = dict(source_candidate.metadata.get("generator") or {})
        with Image.open(base_path) as base_image:
            product_bbox = tuple(generator_meta.get("product_bbox") or self._product_anchor_box(page.template_id, *base_image.size))
        compose_meta = self._compose_text_document(
            base_path=base_path, text_path=text_path, output_path=composed_path,
            document=text_document, product_bbox=product_bbox,
        )
        review_prompt = self._content_review_prompt(project.profile, page)
        reference_strategy = str(recipe.model_params.get("reference_strategy") or "model_edit")
        review_plan = self._build_review_plan(project.profile, page, reference_paths, reference_strategy=reference_strategy)
        qa = self._inspect(
            project.profile, page, reference_paths, generator_meta, compose_meta,
            1, base_path, composed_path, review_prompt, review_plan,
        ) if run_qa else {
            "status": "pending", "score": source_candidate.score, "issues": [],
            "evidence": {"qa_execution": "not_run", "reason": "等待用户手动质检或人工确认"},
            "suggested_fix": "",
        }
        return ProducedCandidate(
            candidate_index=1, base_path=source_candidate.base_path,
            text_layer_path=self._relative(text_path), composed_path=self._relative(composed_path),
            prompt=source_candidate.prompt, score=int(qa["score"]), rank=1,
            qa_status=str(qa["status"]), issues=tuple(qa["issues"]), evidence=dict(qa["evidence"]),
            suggested_fix=str(qa["suggested_fix"]), repair_applied=False,
            metadata={
                **source_candidate.metadata, "generator": generator_meta, "composition": compose_meta,
                "recomposed_from": source_candidate.id, "text_document_version": text_document.version,
                "qa_execution": "completed" if run_qa else "not_run",
                "review_plan": review_plan, "content_review_prompt": review_prompt,
                "recipe_id": recipe.id, "prompt_version_id": prompt_version.id,
            },
        )

    def inspect_candidate(
        self,
        *,
        project: Project,
        page: PageItem,
        recipe: Recipe,
        prompt_version: PromptVersion,
        candidate: Candidate,
        reference_paths: list[Path],
    ) -> ProducedCandidate:
        generator_meta = dict(candidate.metadata.get("generator") or {})
        compose_meta = dict(candidate.metadata.get("composition") or {})
        reference_strategy = str(recipe.model_params.get("reference_strategy") or "model_edit")
        review_prompt = self._content_review_prompt(project.profile, page)
        review_plan = self._build_review_plan(project.profile, page, reference_paths, reference_strategy=reference_strategy)
        qa = self._inspect(
            project.profile, page, reference_paths, generator_meta, compose_meta, 1,
            self.resolve(candidate.base_path), self.resolve(candidate.composed_path), review_prompt, review_plan,
        )
        return ProducedCandidate(
            candidate_index=candidate.candidate_index, base_path=candidate.base_path,
            text_layer_path=candidate.text_layer_path, composed_path=candidate.composed_path,
            prompt=candidate.prompt, score=int(qa["score"]), rank=candidate.rank,
            qa_status=str(qa["status"]), issues=tuple(qa["issues"]), evidence=dict(qa["evidence"]),
            suggested_fix=str(qa["suggested_fix"]), repair_applied=False,
            metadata=candidate.metadata,
        )

    def edit_candidate(
        self,
        *,
        project: Project,
        page: PageItem,
        recipe: Recipe,
        prompt_version: PromptVersion,
        source_candidate: Candidate,
        instruction: str,
        quality: str,
        reference_paths: list[Path],
        progress: Callable[[str, int, dict[str, Any]], None] | None = None,
    ) -> ProducedCandidate:
        def report(stage: str, percent: int, **details: Any) -> None:
            if progress:
                progress(stage, max(0, min(100, percent)), details)

        source_base = self.resolve(source_candidate.base_path)
        template = self._layout_spec(page.template_id)
        source_generator = dict(source_candidate.metadata.get("generator") or {})
        source_effective = dict(source_candidate.metadata.get("effective_generation") or {})
        with Image.open(source_base) as image:
            actual_size = f"{image.width}x{image.height}"
            source_product_bbox = tuple(
                source_generator.get("product_bbox")
                or self._product_anchor_box(page.template_id, image.width, image.height)
            )
        generation_size = str(source_effective.get("size") or source_generator.get("actual_size") or actual_size)
        generation_quality = validate_image_quality(
            quality or str(source_effective.get("quality") or recipe.model_params.get("quality") or "high")
        )
        validate_image_size(generation_size)
        edit_prompt = self._bind_candidate_edit_prompt(
            source_candidate.prompt, instruction, page, template
        )
        report("understanding_edit", 8, label="理解单图修改要求并建立验收计划")
        if self._quality_toolkit and hasattr(self._quality_toolkit, "edit_review_plan"):
            edit_plan = self._quality_toolkit.edit_review_plan(
                instruction,
                source_image_path=source_base,
                product_reference_path=reference_paths[0] if reference_paths else None,
            )
        else:
            edit_plan = {
                "mode": "edit", "source": "production-structured", "summary": instruction,
                "edit_target": instruction,
                "must_preserve": ["未要求修改的商品主体、构图、背景、品牌标识和非目标区域"],
                "review_checks": ["修改要求符合度", "商品一致性", "非目标区域稳定", "视觉质量"],
            }
        run_root = self._root / project.id / page.id / str(uuid4()) / "candidate_edit"
        base_path = run_root / "base.png"
        text_path = run_root / "text_layer.png"
        composed_path = run_root / "composed.png"
        report("editing_candidate", 20, label="Azure 正在以所选无字底图为输入执行定向修改")
        generator_meta = self._generator.edit(
            prompt=edit_prompt,
            profile=project.profile,
            source_base_path=source_base,
            reference_paths=reference_paths,
            output_path=base_path,
            size=generation_size,
            quality=generation_quality,
            layout=template,
        )
        with Image.open(base_path) as generated_image:
            canvas_size = generated_image.size
            product_bbox = tuple(generator_meta.get("product_bbox") or source_product_bbox)
            generator_meta["layout"] = {
                "template_id": page.template_id,
                "template_key": template.get("template_key") or page.template_id,
                "template_version": int(template.get("version", 1)),
                "library_id": template.get("library_id") or "",
                "canvas_size": template.get("size") or generation_size,
                "reserved_text_box": list(self._text_box(page.template_id, *canvas_size)),
                "reserved_title_box": list(self._scaled_box(template.get("title_box") or template["text_box"], *canvas_size)),
                "reserved_body_box": list(self._scaled_box(template.get("body_box") or template["text_box"], *canvas_size)),
                "product_anchor_box": list(self._product_anchor_box(page.template_id, *canvas_size)),
                "allowed_product_extent_box": list(self._product_box(page.template_id, *canvas_size)),
            }
            generator_meta["product_bbox"] = list(product_bbox)
        report("compositing_text", 68, label="重新应用独立文字层")
        compose_meta = self._compose(
            base_path=base_path, text_path=text_path, output_path=composed_path,
            page=page, product_bbox=product_bbox,
        )
        report("checking_edit", 76, label="对比修改前后并执行局部质检")
        qa = self._inspect(
            project.profile, page, reference_paths, generator_meta, compose_meta,
            1, base_path, composed_path, edit_prompt, edit_plan,
            progress=lambda stage, details: report(
                stage,
                {"checking_base_text": 78, "checking_reference": 82, "ocr_output": 86,
                 "ocr_reference": 89, "llm_review": 92}.get(stage, 80),
                **details,
            ),
            review_mode="edit",
            source_image_path=source_base,
        )
        row: dict[str, Any] = {
            "candidate_index": 1,
            "base_path": self._relative(base_path),
            "text_layer_path": self._relative(text_path),
            "composed_path": self._relative(composed_path),
            "prompt": edit_prompt,
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
                "effective_generation": {
                    "size": generation_size, "quality": generation_quality,
                    "template_id": page.template_id, "reference_strategy": "candidate_edit",
                    "max_auto_regenerations": 0,
                },
                "generation_kind": "candidate_edit",
                "source_candidate_id": source_candidate.id,
                "user_instruction": instruction,
                "review_plan": edit_plan,
                "content_review_prompt": edit_prompt,
                "repair_prompt": "",
            },
        }
        if self._quality_toolkit:
            ranked = self._quality_toolkit.rank([row])[1]
            row["score"] = int(ranked["score"]["overall"])
            row["metadata"]["score_breakdown"] = ranked["score"]["breakdown"]
        report("finalizing", 98, label="保存修改版本、文字层与质检结果")
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
        typography: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        template = self._layout_spec(page.template_id)
        if template.get("title_box") and template.get("body_box"):
            return self._compose_separate_text_regions(
                base_path=base_path,
                text_path=text_path,
                output_path=output_path,
                page=page,
                product_bbox=product_bbox,
                typography=typography,
                template=template,
            )
        styles = typography or {}
        base = Image.open(base_path).convert("RGBA")
        width, height = base.size
        layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        safe_area = (int(width * .065), int(height * .055), int(width * .935), int(height * .945))
        text_box = self._text_box(page.template_id, width, height)
        short_edge = min(width, height)
        requested_title_size = int(styles.get("title_font_size") or round(short_edge * {1: .065, 2: .058, 3: .052, 4: .047, 5: .042}.get(page.heading_level, .058)))
        requested_body_size = int(styles.get("body_font_size") or round(short_edge * .029))
        title_size = requested_title_size
        body_size = requested_body_size
        title_min = min(requested_title_size, max(24, round(short_edge * .033)))
        body_min = min(requested_body_size, max(18, round(short_edge * .018)))
        title_spacing = int(styles.get("title_line_spacing") if styles.get("title_line_spacing") is not None else max(8, round(short_edge * .006)))
        body_spacing = int(styles.get("body_line_spacing") if styles.get("body_line_spacing") is not None else max(6, round(short_edge * .0045)))
        title_body_gap = int(styles.get("title_body_gap") if styles.get("title_body_gap") is not None else max(18, round(short_edge * .018)))
        font_family = str(styles.get("font_family") or "system_sans")
        text_align = str(styles.get("text_align") or "left")
        vertical_align = str(styles.get("vertical_align") or "top")
        offset_x = int(styles.get("offset_x") or 0)
        offset_y = int(styles.get("offset_y") or 0)
        text_width = text_box[2] - text_box[0]
        text_height = text_box[3] - text_box[1]
        fit_width = max(80, text_width - abs(offset_x))
        while True:
            title_lines, title_font = self._fit_lines(
                draw, page.title, fit_width, title_size, title_min, 2, font_family
            )
            body_lines, body_font = self._fit_lines(
                draw, page.body, fit_width, body_size, body_min, 4, font_family
            )
            title_preview = "\n".join(title_lines)
            body_preview = "\n".join(body_lines)
            title_preview_bbox = draw.multiline_textbbox(
                (0, 0), title_preview, font=title_font, spacing=title_spacing, align=text_align
            )
            body_preview_bbox = draw.multiline_textbbox(
                (0, 0), body_preview, font=body_font, spacing=body_spacing, align=text_align
            )
            title_width = title_preview_bbox[2] - title_preview_bbox[0]
            body_width = body_preview_bbox[2] - body_preview_bbox[0]
            title_height = title_preview_bbox[3] - title_preview_bbox[1]
            body_height = body_preview_bbox[3] - body_preview_bbox[1]
            block_height = (
                title_height + title_body_gap + body_height
            )
            if block_height <= text_height or (title_font.size <= title_min and body_font.size <= body_min):
                break
            title_size = max(title_min, title_font.size - 2)
            body_size = max(body_min, body_font.size - 2)

        if vertical_align == "center":
            requested_block_top = text_box[1] + (text_height - block_height) // 2 + offset_y
        elif vertical_align == "bottom":
            requested_block_top = text_box[3] - block_height + offset_y
        else:
            requested_block_top = text_box[1] + offset_y
        block_top = min(max(text_box[1], requested_block_top), max(text_box[1], text_box[3] - block_height))

        def aligned_origin(measured_bbox: tuple[int, int, int, int], measured_width: int) -> int:
            if text_align == "center":
                requested_left = text_box[0] + (text_width - measured_width) // 2 + offset_x
            elif text_align == "right":
                requested_left = text_box[2] - measured_width + offset_x
            else:
                requested_left = text_box[0] + offset_x
            visible_left = min(max(text_box[0], requested_left), max(text_box[0], text_box[2] - measured_width))
            return visible_left - measured_bbox[0]

        title_x = aligned_origin(title_preview_bbox, title_width)
        body_x = aligned_origin(body_preview_bbox, body_width)
        title_y = block_top - title_preview_bbox[1]
        body_top = block_top + title_height + title_body_gap
        body_y = body_top - body_preview_bbox[1]
        title_text = "\n".join(title_lines)
        body_text = "\n".join(body_lines)
        title_bbox = draw.multiline_textbbox((title_x, title_y), title_text, font=title_font, spacing=title_spacing, align=text_align)
        body_bbox = draw.multiline_textbbox((body_x, body_y), body_text, font=body_font, spacing=body_spacing, align=text_align)
        rendered_bbox = (
            min(title_bbox[0], body_bbox[0]), min(title_bbox[1], body_bbox[1]),
            max(title_bbox[2], body_bbox[2]), max(title_bbox[3], body_bbox[3]),
        )
        # Sample only the pixels the copy will actually cover. A wide reserved
        # box can contain unrelated dark furniture even when the wall directly
        # behind the copy is bright, which previously selected unreadable white
        # text and caused real OCR false negatives (for example 10kg -> 0kg).
        color_sample_box = (
            max(0, rendered_bbox[0]), max(0, rendered_bbox[1]),
            min(width, rendered_bbox[2]), min(height, rendered_bbox[3]),
        )
        auto_title_color, auto_body_color, auto_color_name = self._text_colors(base, color_sample_box)
        title_color = self._parse_hex_color(styles.get("title_color")) or auto_title_color
        body_color = self._parse_hex_color(styles.get("body_color")) or auto_body_color
        title_color_name = self._rgba_to_hex(title_color)
        body_color_name = self._rgba_to_hex(body_color)
        draw.multiline_text((title_x, title_y), title_text, font=title_font, fill=title_color, spacing=title_spacing, align=text_align)
        draw.multiline_text((body_x, body_y), body_text, font=body_font, fill=body_color, spacing=body_spacing, align=text_align)
        text_path.parent.mkdir(parents=True, exist_ok=True)
        layer.save(text_path, format="PNG")
        Image.alpha_composite(base, layer).convert("RGB").save(output_path, format="PNG")
        repair_applied = (
            title_font.size < requested_title_size
            or body_font.size < requested_body_size
            or block_top != requested_block_top
        )
        font_path = self._font_paths.get(font_family) or self._font_path
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
            "font": font_path.name if font_path else "PillowDefault",
            "font_family": font_family,
            "text_color": auto_color_name if not styles.get("title_color") and not styles.get("body_color") else f"{title_color_name}/{body_color_name}",
            "title_color": title_color_name,
            "body_color": body_color_name,
            "text_align": text_align,
            "vertical_align": vertical_align,
            "offset_x": offset_x,
            "offset_y": offset_y,
            "title_line_spacing": title_spacing,
            "body_line_spacing": body_spacing,
            "title_body_gap": title_body_gap,
            "typography_overrides": dict(styles),
            "background_luminance": round(self._region_luminance(base, color_sample_box), 2),
            "color_sample_box": list(color_sample_box),
            "repair_applied": repair_applied,
        }

    def _compose_separate_text_regions(
        self,
        *,
        base_path: Path,
        text_path: Path,
        output_path: Path,
        page: PageItem,
        product_bbox: tuple[int, int, int, int],
        typography: dict[str, Any] | None,
        template: dict[str, Any],
    ) -> dict[str, Any]:
        styles = typography or {}
        base = Image.open(base_path).convert("RGBA")
        width, height = base.size
        layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        title_box = self._scaled_box(template["title_box"], width, height)
        body_box = self._scaled_box(template["body_box"], width, height)
        text_box = (
            min(title_box[0], body_box[0]), min(title_box[1], body_box[1]),
            max(title_box[2], body_box[2]), max(title_box[3], body_box[3]),
        )
        safe_area = self._scaled_box(template.get("safe_area_box") or (.065, .055, .935, .945), width, height)
        short_edge = min(width, height)
        requested_title_size = int(styles.get("title_font_size") or round(short_edge * {1: .065, 2: .058, 3: .052, 4: .047, 5: .042}.get(page.heading_level, .058)))
        requested_body_size = int(styles.get("body_font_size") or round(short_edge * .029))
        title_min = min(requested_title_size, max(24, round(short_edge * .028)))
        body_min = min(requested_body_size, max(18, round(short_edge * .016)))
        title_spacing = int(styles.get("title_line_spacing") if styles.get("title_line_spacing") is not None else max(8, round(short_edge * .006)))
        body_spacing = int(styles.get("body_line_spacing") if styles.get("body_line_spacing") is not None else max(6, round(short_edge * .0045)))
        title_body_gap = int(styles.get("title_body_gap") if styles.get("title_body_gap") is not None else max(18, round(short_edge * .018)))
        font_family = str(styles.get("font_family") or "system_sans")
        text_align = str(styles.get("text_align") or "left")
        vertical_align = str(styles.get("vertical_align") or "top")
        offset_x = int(styles.get("offset_x") or 0)
        offset_y = int(styles.get("offset_y") or 0)

        def fit_region(
            copy: str,
            region: tuple[int, int, int, int],
            requested_size: int,
            minimum_size: int,
            maximum_lines: int,
            spacing: int,
        ) -> tuple[list[str], ImageFont.FreeTypeFont | ImageFont.ImageFont, tuple[int, int, int, int], int, int, int, bool]:
            region_width = region[2] - region[0]
            region_height = region[3] - region[1]
            fit_width = max(80, region_width - abs(offset_x))
            size = requested_size
            shrunk = False
            while True:
                lines, font = self._fit_lines(draw, copy, fit_width, size, minimum_size, maximum_lines, font_family)
                rendered = "\n".join(lines)
                measured = draw.multiline_textbbox((0, 0), rendered, font=font, spacing=spacing, align=text_align)
                measured_width = measured[2] - measured[0]
                measured_height = measured[3] - measured[1]
                if measured_height <= region_height or font.size <= minimum_size:
                    break
                size = max(minimum_size, font.size - 2)
                shrunk = True
            if text_align == "center":
                requested_left = region[0] + (region_width - measured_width) // 2 + offset_x
            elif text_align == "right":
                requested_left = region[2] - measured_width + offset_x
            else:
                requested_left = region[0] + offset_x
            visible_left = min(max(region[0], requested_left), max(region[0], region[2] - measured_width))
            if vertical_align == "center":
                requested_top = region[1] + (region_height - measured_height) // 2 + offset_y
            elif vertical_align == "bottom":
                requested_top = region[3] - measured_height + offset_y
            else:
                requested_top = region[1] + offset_y
            visible_top = min(max(region[1], requested_top), max(region[1], region[3] - measured_height))
            origin_x = visible_left - measured[0]
            origin_y = visible_top - measured[1]
            clamped = visible_left != requested_left or visible_top != requested_top
            return lines, font, measured, origin_x, origin_y, measured_height, shrunk or clamped

        title_lines, title_font, _, title_x, title_y, _, title_repaired = fit_region(
            page.title, title_box, requested_title_size, title_min, 2, title_spacing,
        )
        body_lines, body_font, _, body_x, body_y, _, body_repaired = fit_region(
            page.body, body_box, requested_body_size, body_min, 4, body_spacing,
        )
        title_text = "\n".join(title_lines)
        body_text = "\n".join(body_lines)
        title_bbox = draw.multiline_textbbox((title_x, title_y), title_text, font=title_font, spacing=title_spacing, align=text_align)
        body_bbox = draw.multiline_textbbox((body_x, body_y), body_text, font=body_font, spacing=body_spacing, align=text_align)
        rendered_bbox = (
            min(title_bbox[0], body_bbox[0]), min(title_bbox[1], body_bbox[1]),
            max(title_bbox[2], body_bbox[2]), max(title_bbox[3], body_bbox[3]),
        )
        color_sample_box = (
            max(0, rendered_bbox[0]), max(0, rendered_bbox[1]),
            min(width, rendered_bbox[2]), min(height, rendered_bbox[3]),
        )
        auto_title_color, auto_body_color, auto_color_name = self._text_colors(base, color_sample_box)
        title_color = self._parse_hex_color(styles.get("title_color")) or auto_title_color
        body_color = self._parse_hex_color(styles.get("body_color")) or auto_body_color
        title_color_name = self._rgba_to_hex(title_color)
        body_color_name = self._rgba_to_hex(body_color)
        draw.multiline_text((title_x, title_y), title_text, font=title_font, fill=title_color, spacing=title_spacing, align=text_align)
        draw.multiline_text((body_x, body_y), body_text, font=body_font, fill=body_color, spacing=body_spacing, align=text_align)
        text_path.parent.mkdir(parents=True, exist_ok=True)
        layer.save(text_path, format="PNG")
        Image.alpha_composite(base, layer).convert("RGB").save(output_path, format="PNG")
        font_path = self._font_paths.get(font_family) or self._font_path
        return {
            "canvas": [width, height],
            "safe_area": list(safe_area),
            "text_box": list(text_box),
            "title_box": list(title_box),
            "body_box": list(body_box),
            "rendered_text_bbox": list(rendered_bbox),
            "rendered_title_bbox": list(title_bbox),
            "rendered_body_bbox": list(body_bbox),
            "product_bbox": list(product_bbox),
            "title_font_size": title_font.size,
            "title_lines": title_lines,
            "heading_level": page.heading_level,
            "body_font_size": body_font.size,
            "body_lines": body_lines,
            "font": font_path.name if font_path else "PillowDefault",
            "font_family": font_family,
            "text_color": auto_color_name if not styles.get("title_color") and not styles.get("body_color") else f"{title_color_name}/{body_color_name}",
            "title_color": title_color_name,
            "body_color": body_color_name,
            "text_align": text_align,
            "vertical_align": vertical_align,
            "offset_x": offset_x,
            "offset_y": offset_y,
            "title_line_spacing": title_spacing,
            "body_line_spacing": body_spacing,
            "title_body_gap": title_body_gap,
            "typography_overrides": dict(styles),
            "background_luminance": round(self._region_luminance(base, color_sample_box), 2),
            "color_sample_box": list(color_sample_box),
            "repair_applied": title_repaired or body_repaired or title_font.size < requested_title_size or body_font.size < requested_body_size,
        }

    def _compose_text_document(
        self,
        *,
        base_path: Path,
        text_path: Path,
        output_path: Path,
        document: TextDocument,
        product_bbox: tuple[int, int, int, int],
    ) -> dict[str, Any]:
        base = Image.open(base_path).convert("RGBA")
        width, height = base.size
        safe_area = self._scaled_box((.055, .045, .945, .955), width, height)
        layer_canvas = Image.new("RGBA", base.size, (0, 0, 0, 0))
        rendered: list[dict[str, Any]] = []
        repaired = False
        for text_layer in sorted(document.layers, key=lambda item: item.z_index):
            if not text_layer.visible or not text_layer.content:
                continue
            region = self._scaled_box(text_layer.box, width, height)
            region_width = max(1, region[2] - region[0])
            region_height = max(1, region[3] - region[1])
            padding = min(text_layer.padding, region_width // 3, region_height // 3)
            content_region = (
                region[0] + padding, region[1] + padding,
                region[2] - padding, region[3] - padding,
            )
            if text_layer.background_color and text_layer.background_opacity > 0:
                background = self._parse_hex_color(text_layer.background_color) or (255, 255, 255, 255)
                fill = (*background[:3], round(255 * text_layer.background_opacity * text_layer.opacity))
                ImageDraw.Draw(layer_canvas).rounded_rectangle(region, radius=max(0, padding), fill=fill)
            scratch = Image.new("RGBA", (region_width, region_height), (0, 0, 0, 0))
            draw = ImageDraw.Draw(scratch)
            fit_width = max(8, content_region[2] - content_region[0])
            fit_height = max(8, content_region[3] - content_region[1])
            size = text_layer.font_size
            minimum = max(8, min(size, round(min(width, height) * .012)))
            while True:
                font = self._font(size, text_layer.font_family)
                lines = self._wrap_spaced(draw, text_layer.content, font, fit_width, text_layer.letter_spacing)
                spacing = max(0, round(size * max(0, text_layer.line_height - 1)))
                text = "\n".join(lines)
                bbox = draw.multiline_textbbox(
                    (0, 0), text, font=font, spacing=spacing, align=text_layer.text_align,
                    stroke_width=text_layer.stroke_width,
                )
                measured_width, measured_height = bbox[2] - bbox[0], bbox[3] - bbox[1]
                if text_layer.letter_spacing:
                    measured_width = max(
                        (round(self._spaced_text_width(draw, line, font, text_layer.letter_spacing)) for line in lines),
                        default=0,
                    )
                if measured_height <= fit_height and measured_width <= fit_width or size <= minimum:
                    break
                size = max(minimum, size - max(1, round(size * .04)))
                repaired = True
            if text_layer.text_align == "center":
                x = (region_width - measured_width) // 2 - bbox[0]
            elif text_layer.text_align == "right":
                x = region_width - padding - measured_width - bbox[0]
            else:
                x = padding - bbox[0]
            if text_layer.vertical_align == "center":
                y = (region_height - measured_height) // 2 - bbox[1]
            elif text_layer.vertical_align == "bottom":
                y = region_height - padding - measured_height - bbox[1]
            else:
                y = padding - bbox[1]
            fill = self._parse_hex_color(text_layer.color) or (24, 31, 28, 255)
            fill = (*fill[:3], round(255 * text_layer.opacity))
            stroke_fill = self._parse_hex_color(text_layer.stroke_color) or (255, 255, 255, 255)
            synthetic_bold = max(0, (text_layer.font_weight - 500) // 200)
            effective_stroke = text_layer.stroke_width + synthetic_bold
            def draw_copy(target: ImageDraw.ImageDraw, origin_x: int, origin_y: int, color: tuple[int, int, int, int]) -> None:
                if not text_layer.letter_spacing:
                    target.multiline_text(
                        (origin_x, origin_y), text, font=font, spacing=spacing,
                        align=text_layer.text_align, fill=color,
                        stroke_width=effective_stroke, stroke_fill=stroke_fill,
                    )
                    return
                cursor_y = origin_y
                line_height = max(1, font.getbbox("国Ag")[3] - font.getbbox("国Ag")[1])
                for line in lines:
                    line_width = self._spaced_text_width(target, line, font, text_layer.letter_spacing)
                    if text_layer.text_align == "center":
                        cursor_x = (region_width - line_width) / 2
                    elif text_layer.text_align == "right":
                        cursor_x = region_width - padding - line_width
                    else:
                        cursor_x = padding
                    for char in line:
                        target.text(
                            (round(cursor_x), cursor_y), char, font=font, fill=color,
                            stroke_width=effective_stroke, stroke_fill=stroke_fill,
                        )
                        cursor_x += target.textlength(char, font=font) + text_layer.letter_spacing
                    cursor_y += line_height + spacing
            if text_layer.shadow:
                shadow_fill = self._parse_hex_color(text_layer.shadow_color) or (0, 0, 0, 255)
                shadow = Image.new("RGBA", scratch.size, (0, 0, 0, 0))
                draw_copy(
                    ImageDraw.Draw(shadow), x + text_layer.shadow_offset_x, y + text_layer.shadow_offset_y,
                    (*shadow_fill[:3], round(170 * text_layer.opacity)),
                )
                if text_layer.shadow_blur:
                    shadow = shadow.filter(ImageFilter.GaussianBlur(text_layer.shadow_blur))
                scratch.alpha_composite(shadow)
            draw_copy(ImageDraw.Draw(scratch), x, y, fill)
            decoration_draw = ImageDraw.Draw(scratch)
            decoration_width = max(1, round(size / 18) + synthetic_bold)
            if text_layer.underline:
                underline_y = min(region_height - 1, y + measured_height + max(1, round(size * .05)))
                decoration_draw.line((x, underline_y, x + measured_width, underline_y), fill=fill, width=decoration_width)
            if text_layer.strikethrough:
                strike_y = min(region_height - 1, y + max(1, round(measured_height * .52)))
                decoration_draw.line((x, strike_y, x + measured_width, strike_y), fill=fill, width=decoration_width)
            if text_layer.font_style == "italic":
                shear = -.18
                scratch = scratch.transform(
                    scratch.size, Image.Transform.AFFINE, (1, shear, max(0, round(region_height * .18)), 0, 1, 0),
                    resample=Image.Resampling.BICUBIC,
                )
            if text_layer.rotation:
                scratch = scratch.rotate(-text_layer.rotation, resample=Image.Resampling.BICUBIC, expand=False)
            layer_canvas.alpha_composite(scratch, (region[0], region[1]))
            rendered.append({
                **text_layer.to_dict(),
                "id": text_layer.id, "role": text_layer.role, "box": list(region),
                "font_family": text_layer.font_family, "requested_font_size": text_layer.font_size,
                "font_weight": text_layer.font_weight, "font_style": text_layer.font_style,
                "underline": text_layer.underline, "strikethrough": text_layer.strikethrough,
                "font_size": size, "lines": lines, "color": text_layer.color,
                "text_align": text_layer.text_align, "vertical_align": text_layer.vertical_align,
                "rotation": text_layer.rotation, "content": text_layer.content,
                "stroke_width": text_layer.stroke_width, "synthetic_bold_width": synthetic_bold,
                "effective_stroke_width": effective_stroke,
                "stroke_color": text_layer.stroke_color, "shadow": text_layer.shadow,
            })
        text_path.parent.mkdir(parents=True, exist_ok=True)
        layer_canvas.save(text_path, format="PNG")
        Image.alpha_composite(base, layer_canvas).convert("RGB").save(output_path, format="PNG")
        boxes = [item["box"] for item in rendered]
        union_box = [
            min((box[0] for box in boxes), default=0), min((box[1] for box in boxes), default=0),
            max((box[2] for box in boxes), default=0), max((box[3] for box in boxes), default=0),
        ]
        return {
            "canvas": [width, height], "safe_area": list(safe_area), "text_box": union_box,
            "rendered_text_bbox": union_box, "product_bbox": list(product_bbox),
            "text_layers": rendered, "text_document_version": document.version,
            "text_layer_stored_separately": True, "base_contains_post_layout_text": False,
            "font": ", ".join(dict.fromkeys(item["font_family"] for item in rendered)) or "none",
            "text_color": ", ".join(dict.fromkeys(item["color"] for item in rendered)) or "none",
            "repair_applied": repaired,
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
        progress: Callable[[str, dict[str, Any]], None] | None = None,
        review_mode: str = "generate",
        source_image_path: Path | None = None,
    ) -> dict[str, Any]:
        def report(stage: str, **details: Any) -> None:
            if progress:
                progress(stage, details)

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
                report("checking_base_text", label="OCR 检查底图留白区")
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
                report("checking_reference", label="核对参考商品与布局")
                bbox_source = str(generator_meta.get("product_bbox_source") or "")
                similarity_box = generator_meta.get("product_bbox")
                if bbox_source == "layered_reference":
                    reference_similarity = 1.0
                elif similarity_box and bbox_source != "model_generated_target_region":
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
                visual_reference = source_image_path or reference_paths[0]
                visual_review = self._quality_toolkit.visual_evidence(visual_reference, output_path, target_region)
            elif source_image_path:
                report("checking_reference", label="对比修改前后与非目标区域")
                visual_review = self._quality_toolkit.visual_evidence(
                    source_image_path, output_path, (0.0, 0.0, 1.0, 1.0)
                )

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
                    "product_generated_by_model": generator_meta.get("product_generated_by_model", False),
                }
                combined_review = self._quality_toolkit.review_candidate(
                    output_path=output_path,
                    reference_path=reference_paths[0] if reference_paths else None,
                    reference_paths=reference_paths,
                    prompt=prompt,
                    review_plan=review_plan,
                    visual_review=visual_review,
                    generation={**generator_meta, "composition_provenance": composition_provenance},
                    title=page.title,
                    body=page.body,
                    bbox=bbox,
                    number_allowlist=copy_number_allowlist,
                    progress=lambda stage: report(
                        stage,
                        label={
                            "ocr_output": "OCR 校验最终营销文案",
                            "ocr_reference": "OCR 读取参考商品面板",
                            "llm_review": "LLM 审查视觉质量与参考一致性",
                        }.get(stage, "执行质量审查"),
                    ),
                    mode=review_mode,
                    source_image_path=source_image_path,
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
                    self._llm_issue_severity(category, review_issue.get("severity", "P2")),
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
                "layout": {
                    "canvas": compose_meta["canvas"],
                    "safe_area": list(safe),
                    "text_bbox": list(rendered),
                    "title_box": list(compose_meta.get("title_box") or compose_meta["text_box"]),
                    "body_box": list(compose_meta.get("body_box") or compose_meta["text_box"]),
                    "subject_bbox": list(product),
                    "subject_anchor_box": list((generator_meta.get("layout") or {}).get("product_anchor_box") or product),
                    "subject_allowed_box": list((generator_meta.get("layout") or {}).get("allowed_product_extent_box") or product),
                    "overlap_ratio": round(overlap, 4),
                },
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
                "reference_consistency": {
                    "reference_count": len(reference_paths),
                    "generator_source": generator_meta.get("source_reference", ""),
                    "generator_sources": generator_meta.get("source_references", []),
                    "product_generated_by_model": generator_meta.get("product_generated_by_model", False),
                    "product_similarity": reference_similarity,
                },
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
            "综合全部商品外观图和局部细节图判断同一商品身份：允许按视觉目标生成新角度、透视、"
            "环境光影和效果，但商品轮廓、比例、颜色、材质、门体、把手、控制面板及关键结构应保持一致"
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
                "product_generated_by_model": reference_strategy == "model_edit" and bool(reference_paths),
                "reference_image_count": len(reference_paths),
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
        font_family: str = "system_sans",
    ) -> tuple[list[str], ImageFont.FreeTypeFont | ImageFont.ImageFont]:
        normalized = text.strip() or " "
        for size in range(start_size, min_size - 1, -2):
            font = self._font(size, font_family)
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
        font = self._font(min_size, font_family)
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

    @staticmethod
    def _spaced_text_width(
        draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, letter_spacing: float,
    ) -> float:
        return sum(draw.textlength(char, font=font) for char in text) + max(0, len(text) - 1) * letter_spacing

    @classmethod
    def _wrap_spaced(
        cls, draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont,
        max_width: int, letter_spacing: float,
    ) -> list[str]:
        if not letter_spacing:
            return cls._wrap(draw, text, font, max_width)
        lines: list[str] = []
        for paragraph in text.splitlines() or [""]:
            current = ""
            for char in paragraph:
                candidate = current + char
                if current and cls._spaced_text_width(draw, candidate, font, letter_spacing) > max_width:
                    lines.append(current)
                    current = char
                else:
                    current = candidate
            lines.append(current)
        return lines or [""]

    def _font(self, size: int, family: str = "system_sans") -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        path = (self._font_resolver(family) if self._font_resolver else None) or self._font_paths.get(family) or self._font_path
        return ImageFont.truetype(str(path), size) if path else ImageFont.load_default(size=size)

    @staticmethod
    def _parse_hex_color(value: Any) -> tuple[int, int, int, int] | None:
        if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
            return None
        return tuple(bytes.fromhex(value[1:])) + (255,)

    @staticmethod
    def _rgba_to_hex(color: tuple[int, int, int, int]) -> str:
        return "#" + "".join(f"{channel:02X}" for channel in color[:3])

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
    def _first_font(candidates: list[Path]) -> Path | None:
        return next((path for path in candidates if path.exists()), None)

    @classmethod
    def _find_fonts(cls) -> dict[str, Path | None]:
        configured = os.environ.get("PCP_FONT_PATH", "").strip()
        windows_fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        configured_fonts = [Path(configured)] if configured else []
        sans = cls._first_font(configured_fonts + [
                windows_fonts / "msyh.ttc",
                windows_fonts / "Deng.ttf",
                windows_fonts / "simhei.ttf",
                Path("/System/Library/Fonts/PingFang.ttc"),
                Path("/System/Library/Fonts/STHeiti Light.ttc"),
                Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
                Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
                Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        ])
        bold = cls._first_font(configured_fonts + [
            windows_fonts / "msyhbd.ttc",
            windows_fonts / "simhei.ttf",
            Path("/System/Library/Fonts/PingFang.ttc"),
            Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ]) or sans
        serif = cls._first_font(configured_fonts + [
            windows_fonts / "simsun.ttc",
            Path("/System/Library/Fonts/Supplemental/Songti.ttc"),
            Path("/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"),
        ]) or sans
        return {"system_sans": sans, "system_bold": bold, "system_serif": serif}

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

    @staticmethod
    def _scaled_box(box: Any, width: int, height: int) -> tuple[int, int, int, int]:
        x1, y1, x2, y2 = box
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

    @staticmethod
    def _llm_issue_severity(category: str, severity: str) -> str:
        """Keep subjective multimodal opinions advisory instead of release-blocking.

        Text accuracy, numeric facts, safe-area geometry and exact reference-layer
        provenance are enforced separately with deterministic evidence. Visual
        taste and prompt-style judgements remain useful review signals, but an
        LLM should not promote them to P0/P1 and block an otherwise verifiable
        deliverable.
        """
        normalized = severity if severity in {"P0", "P1", "P2", "P3"} else "P2"
        if category in {"layout_position", "prompt_following", "visual_quality"} and normalized in {"P0", "P1"}:
            return "P2"
        return normalized

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
                result = result.replace(f"（{copy}）", "").replace(f"({copy})", "")
                result = result.replace(copy, "")
        result = result.replace("（）", "").replace("()", "")
        product_guardrail = (
            "最高优先级：商品将由系统在生图后从用户参考图中原样抠出并合成。你只生成空置场景底图，"
            "不要生成、绘制、复制或暗示任何商品、家电、机器、展台占位块、商品轮廓或商品文字；"
            "在模板商品允许区域保留连续、自然、可承接商品层的墙面和地面，并保持光向一致。"
            if reference_strategy == "layered_product"
            else (
                "最高优先级：输入的全部商品外观图和局部细节图共同定义同一件商品。"
                "必须由模型把商品直接生成在场景中，不能复制粘贴、抠图贴层或把参考图当作平面贴纸；"
                "可以依据视觉目标生成新的拍摄角度、透视、材质反射、环境光影和使用效果，但必须保持"
                "商品身份稳定，包括主体轮廓、长宽比例、主色、材质、门体、把手、控制面板及关键结构。"
                "只生成一件完整商品，不得重复、拼贴、裁切机身、门体或关键结构；让商品与地面接触、"
                "投影、遮挡和环境反射自然一致。"
            )
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

    def _bind_candidate_edit_prompt(
        self,
        original_prompt: str,
        instruction: str,
        page: PageItem,
        template: dict[str, Any],
    ) -> str:
        layout_instruction = str(template.get("instruction") or "")
        return (
            "任务类型：基于输入候选底图的局部编辑。输入的第一张图是当前候选的无营销文字 base.png，"
            "它定义现有商品、角度、构图、背景、光影与空间关系；其余图片是同一商品的外观和细节参考。\n"
            f"用户新增要求：{instruction.strip()}\n"
            f"原始生成意图（仅作上下文，不覆盖新增要求）：{original_prompt.strip()}\n"
            f"模板构图约束：{layout_instruction}。页面视觉目标：{page.visual_goal}。\n"
            "只修改用户明确要求的视觉内容；未点名的商品身份、数量、轮廓、比例、品牌标识、主要结构、"
            "镜头、透视、背景、光向、材质、构图和非目标区域必须尽量保持。不要复制粘贴商品图层，"
            "应由图像编辑模型在原底图中完成自然一致的修改。输出仍是纯视觉底图：不得生成营销标题、"
            "正文、标语、数字标签、水印、文本框、占位符或伪文字；最终标题与正文由系统后期文字层重新排版。"
        )

    def _relative(self, path: Path) -> str:
        return str(path.resolve().relative_to(self._root))
