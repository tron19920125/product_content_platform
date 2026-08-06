from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageOps, ImageStat

from product_content_platform.application.production_ports import BaseImageGenerator, ProducedCandidate
from product_content_platform.domain import Candidate, PageItem, ProductProfile, Project, PromptVersion, Recipe


class LocalProductionEngine:
    """Deep production module: prompt binding, image creation, composition, QA, repair and ranking."""

    def __init__(self, root: Path, generator: BaseImageGenerator, quality_toolkit: Any | None = None) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._generator = generator
        self._quality_toolkit = quality_toolkit
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
        prompt = self._bind_prompt(prompt_version.body, project.profile, page)
        review_plan = self._build_review_plan(prompt, reference_paths)
        run_root = self._root / project.id / page.id / str(uuid4())
        produced: list[dict[str, Any]] = []
        for index in range(1, max(1, min(3, recipe.candidate_count)) + 1):
            candidate_root = run_root / f"candidate_{index}"
            base_path = candidate_root / "base.png"
            text_path = candidate_root / "text_layer.png"
            composed_path = candidate_root / "composed.png"
            generator_meta = self._generator.generate(
                prompt=prompt,
                profile=project.profile,
                reference_paths=reference_paths,
                output_path=base_path,
                variant=index,
            )
            compose_meta = self._compose(
                base_path=base_path,
                text_path=text_path,
                output_path=composed_path,
                page=page,
                product_bbox=tuple(generator_meta.get("product_bbox", (455, 225, 835, 1090))),
            )
            qa = self._inspect(
                project.profile, page, reference_paths, generator_meta, compose_meta,
                index, base_path, composed_path, prompt, review_plan,
            )
            repair_prompt = ""
            if self._quality_toolkit and qa["suggested_fix"]:
                repair_prompt = self._quality_toolkit.repair_prompt(prompt, qa["suggested_fix"], page.title, page.body)
            repair_history: list[dict[str, Any]] = []
            requires_regeneration = any(issue.get("repair") == "regenerate" for issue in qa["issues"])
            if requires_regeneration and repair_prompt:
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
                )
                compose_meta = self._compose(
                    base_path=base_path,
                    text_path=text_path,
                    output_path=composed_path,
                    page=page,
                    product_bbox=tuple(generator_meta.get("product_bbox", (455, 225, 835, 1090))),
                )
                qa = self._inspect(
                    project.profile, page, reference_paths, generator_meta, compose_meta,
                    index, base_path, composed_path, repair_prompt, review_plan,
                )
            produced.append(
                {
                    "candidate_index": index,
                    "base_path": self._relative(base_path),
                    "text_layer_path": self._relative(text_path),
                    "composed_path": self._relative(composed_path),
                    "prompt": prompt,
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
                        "review_plan": review_plan,
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
        prompt = self._bind_prompt(prompt_version.body, project.profile, page)
        review_plan = self._build_review_plan(prompt, reference_paths)
        candidate_root = self._root / project.id / page.id / str(uuid4()) / "recompose"
        text_path = candidate_root / "text_layer.png"
        composed_path = candidate_root / "composed.png"
        base_path = self.resolve(source_candidate.base_path)
        generator_meta = dict(source_candidate.metadata.get("generator") or {})
        compose_meta = self._compose(
            base_path=base_path,
            text_path=text_path,
            output_path=composed_path,
            page=page,
            product_bbox=tuple(generator_meta.get("product_bbox", (455, 225, 835, 1090))),
        )
        qa = self._inspect(
            project.profile, page, reference_paths, generator_meta, compose_meta,
            1, base_path, composed_path, prompt, review_plan,
        )
        row: dict[str, Any] = {
            "candidate_index": 1,
            "base_path": source_candidate.base_path,
            "text_layer_path": self._relative(text_path),
            "composed_path": self._relative(composed_path),
            "prompt": prompt,
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
                "repair_prompt": self._quality_toolkit.repair_prompt(prompt, qa["suggested_fix"], page.title, page.body) if self._quality_toolkit and qa["suggested_fix"] else "",
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
        title_size = {1: 64, 2: 56, 3: 48, 4: 42, 5: 36}.get(page.heading_level, 56)
        body_size = 30
        title_lines, title_font = self._fit_lines(draw, page.title, text_box[2] - text_box[0], title_size, 30, 2)
        body_lines, body_font = self._fit_lines(draw, page.body, text_box[2] - text_box[0], body_size, 20, 5)
        repair_applied = title_font.size < title_size or body_font.size < body_size
        x, y = text_box[0], text_box[1]
        title_text = "\n".join(title_lines)
        draw.multiline_text((x, y), title_text, font=title_font, fill=(250, 253, 251, 255), spacing=12)
        title_bbox = draw.multiline_textbbox((x, y), title_text, font=title_font, spacing=12)
        body_y = title_bbox[3] + 28
        body_text = "\n".join(body_lines)
        draw.multiline_text((x, body_y), body_text, font=body_font, fill=(221, 231, 225, 255), spacing=9)
        body_bbox = draw.multiline_textbbox((x, body_y), body_text, font=body_font, spacing=9)
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
            "heading_level": page.heading_level,
            "body_font_size": body_font.size,
            "font": self._font_path.name if self._font_path else "PillowDefault",
            "text_color": "#FAFDFB",
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
        reference_similarity: float | None = None
        if self._quality_toolkit:
            canvas_width, canvas_height = compose_meta["canvas"]
            bbox = (
                rendered[0] / canvas_width, rendered[1] / canvas_height,
                rendered[2] / canvas_width, rendered[3] / canvas_height,
            )
            if reference_paths:
                reference_similarity = self._reference_similarity(
                    reference_paths[0], base_path, tuple(compose_meta["product_bbox"])
                )
                if reference_similarity < .55:
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
                combined_review = self._quality_toolkit.review_candidate(
                    output_path=output_path,
                    reference_path=reference_paths[0] if reference_paths else None,
                    prompt=prompt,
                    review_plan=review_plan,
                    visual_review=visual_review,
                    generation=generator_meta,
                    title=page.title,
                    body=page.body,
                    bbox=bbox,
                    number_allowlist=allowed_numbers,
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
                    title=page.title, body=page.body, bbox=bbox, number_allowlist=allowed_numbers
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
                "layout": {"canvas": compose_meta["canvas"], "safe_area": list(safe), "text_bbox": list(rendered), "subject_bbox": list(product), "overlap_ratio": round(overlap, 4)},
                "product_facts": {"found_numbers": found_numbers, "allowed_numbers": allowed_numbers, "invented_numbers": invented},
                "reference_consistency": {"reference_count": len(reference_paths), "generator_source": generator_meta.get("source_reference", ""), "product_similarity": reference_similarity},
                "brand_and_multi_page": {"font": compose_meta["font"], "text_color": compose_meta["text_color"], "template_id": page.template_id},
                "text_review": text_review,
                "visual_review": visual_review,
                "multimodal_review": llm_review,
            },
        }

    def _build_review_plan(self, prompt: str, reference_paths: list[Path]) -> dict[str, Any]:
        if not self._quality_toolkit:
            return {}
        reference_path = reference_paths[0] if reference_paths else None
        try:
            return self._quality_toolkit.review_plan(prompt, reference_path=reference_path)
        except TypeError:
            return self._quality_toolkit.review_plan(prompt)

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
            if len(lines) <= max_lines:
                return lines, font
        font = self._font(min_size)
        return self._wrap(draw, normalized, font, max_width), font

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
    def _find_font() -> Path | None:
        for value in (
            "/System/Library/Fonts/STHeiti Light.ttc",
            "/System/Library/Fonts/PingFang.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ):
            path = Path(value)
            if path.exists():
                return path
        return None

    @staticmethod
    def _text_box(template_id: str, width: int, height: int) -> tuple[int, int, int, int]:
        boxes = {
            "hero-center": (.09, .07, .91, .29),
            "split-left": (.07, .11, .43, .82),
            "split-right": (.57, .11, .93, .82),
            "scene-overlay": (.07, .08, .48, .36),
            "data-grid": (.07, .08, .93, .34),
        }
        x1, y1, x2, y2 = boxes.get(template_id, boxes["split-left"])
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
    def _bind_prompt(body: str, profile: ProductProfile, page: PageItem) -> str:
        values = {
            "product_name": profile.name,
            "sku": profile.sku,
            "model": profile.model,
            "category": profile.category,
            "selling_points": "；".join(profile.selling_points),
            "page_title": page.title,
            "page_body": page.body,
            "visual_goal": page.visual_goal,
            "template_id": page.template_id,
        }
        result = body
        for key, value in values.items():
            result = result.replace("{{" + key + "}}", value)
        return result

    def _relative(self, path: Path) -> str:
        return str(path.resolve().relative_to(self._root))
