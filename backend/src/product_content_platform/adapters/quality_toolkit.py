from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable


class ProductQualityToolkit:
    """Deep module exposing OCR, multimodal review, scoring, ranking and repair behind one interface."""

    def __init__(self, workspace_root: Path | None = None, mode: str = "local") -> None:
        if mode not in {"local", "azure"}:
            raise ValueError("质检模式必须是 local 或 azure")
        # The optional path remains accepted to avoid breaking local callers; it is not used.
        _ = workspace_root
        from product_content_platform.quality.azure_vision_ocr import (
            AzureVisionOcrError,
            read_image_text,
        )
        from product_content_platform.quality.scoring import compose_repair_prompt, rank_candidates, score_candidate
        from product_content_platform.quality.llm_reviewer import (
            LlmReviewerError,
            ReviewEvidence,
            review_image_with_llm,
        )
        from product_content_platform.quality.review_planner import create_review_plan, fallback_review_plan
        from product_content_platform.quality.text_review import OcrLine, TextReviewSpec, review_text_ocr
        from product_content_platform.quality.visual_review import review_edit_visuals
        from product_content_platform.integrations.azure_credentials import token_provider_from_env

        self.mode = mode
        self._compose_repair_prompt = compose_repair_prompt
        self._rank_candidates = rank_candidates
        self._score_candidate = score_candidate
        self._read_image_text = read_image_text
        self._azure_vision_ocr_error = AzureVisionOcrError
        self._review_evidence = ReviewEvidence
        self._review_image_with_llm = review_image_with_llm
        self._llm_reviewer_error = LlmReviewerError
        self._create_review_plan = create_review_plan
        self._ocr_line = OcrLine
        self._text_spec = TextReviewSpec
        self._review_text_ocr = review_text_ocr
        self._fallback_review_plan = fallback_review_plan
        self._review_edit_visuals = review_edit_visuals
        if mode == "azure":
            openai_endpoint = (
                os.environ.get("AZURE_OPENAI_REVIEW_ENDPOINT")
                or os.environ.get("AZURE_OPENAI_RESOURCE_ENDPOINT")
                or ""
            )
            vision_endpoint = os.environ.get("AZURE_AI_VISION_ENDPOINT", "")
            self._openai_token_provider = token_provider_from_env(endpoint=openai_endpoint)
            self._vision_token_provider = token_provider_from_env(endpoint=vision_endpoint)
        else:
            self._openai_token_provider = None
            self._vision_token_provider = None

    def review_plan(self, prompt: str, reference_path: Path | None = None) -> dict[str, Any]:
        if self.mode == "azure":
            try:
                return self._create_review_plan(
                    prompt,
                    mode="generate",
                    product_reference_image_path=str(reference_path or ""),
                    timeout=self._positive_int_env("PCP_LLM_REVIEW_TIMEOUT", 120),
                    max_attempts=self._positive_int_env("PCP_LLM_REVIEW_MAX_ATTEMPTS", 3),
                    token_provider=self._openai_token_provider,
                ).to_dict()
            except self._llm_reviewer_error as exc:
                fallback = self._fallback_review_plan(prompt, mode="generate").to_dict()
                fallback["degraded"] = True
                fallback["error"] = str(exc)
                return fallback
        return self._fallback_review_plan(prompt, mode="generate").to_dict()

    def edit_review_plan(
        self,
        prompt: str,
        *,
        source_image_path: Path,
        product_reference_path: Path | None = None,
    ) -> dict[str, Any]:
        if self.mode == "azure":
            try:
                return self._create_review_plan(
                    prompt,
                    mode="edit",
                    source_image_path=str(source_image_path),
                    product_reference_image_path=str(product_reference_path or ""),
                    timeout=self._positive_int_env("PCP_LLM_REVIEW_TIMEOUT", 120),
                    max_attempts=self._positive_int_env("PCP_LLM_REVIEW_MAX_ATTEMPTS", 3),
                    token_provider=self._openai_token_provider,
                ).to_dict()
            except Exception as exc:
                fallback = self._fallback_review_plan(prompt, mode="edit").to_dict()
                fallback["degraded"] = True
                fallback["error"] = str(exc)
                return fallback
        return self._fallback_review_plan(prompt, mode="edit").to_dict()

    def visual_evidence(
        self,
        reference_path: Path,
        output_path: Path,
        target_region: tuple[float, float, float, float],
    ) -> dict[str, Any]:
        return self._review_edit_visuals(
            reference_path,
            output_path,
            target_region=target_region,
            min_target_change=0.0,
            max_outside_change=0.99,
            min_reference_similarity=0.01,
        ).to_dict()

    def review_known_text(
        self,
        *,
        title: str,
        body: str,
        bbox: tuple[float, float, float, float],
        number_allowlist: list[str],
        feature_text: list[str] | None = None,
    ) -> dict[str, Any]:
        expected = [value for value in (title.strip(), body.strip(), *(feature_text or [])) if value]
        result = self._review_text_ocr(
            [self._ocr_line(text="\n".join(expected), confidence=1.0, bbox=bbox)],
            self._text_spec(
                required_text=expected,
                number_allowlist=number_allowlist,
                strict_number_allowlist=False,
                expected_text_region=bbox,
            ),
        )
        return result.to_dict()

    def inspect_reserved_area(
        self,
        image_path: Path,
        bbox: tuple[float, float, float, float],
    ) -> dict[str, Any]:
        """Detect model-generated text inside the region reserved for post-composition copy."""
        if self.mode != "azure":
            return {"provider": "not-run-local", "lines": [], "unexpected_lines": []}
        try:
            lines = self._read_image_text(
                image_path,
                token_provider=self._vision_token_provider,
            )
        except self._azure_vision_ocr_error as exc:
            return {
                "provider": "azure-ai-vision",
                "lines": [],
                "unexpected_lines": [],
                "degraded": True,
                "error": str(exc),
            }
        rows = self._ocr_dicts(lines)
        unexpected = [row for row in rows if self._bbox_center_inside(row.get("bbox"), bbox)]
        return {
            "provider": "azure-ai-vision",
            "lines": rows,
            "unexpected_lines": unexpected,
            "reserved_bbox": bbox,
        }

    def review_candidate(
        self,
        *,
        output_path: Path,
        reference_path: Path | None,
        prompt: str,
        review_plan: dict[str, Any],
        visual_review: dict[str, Any],
        generation: dict[str, Any],
        title: str,
        body: str,
        feature_text: list[str] | None = None,
        bbox: tuple[float, float, float, float],
        number_allowlist: list[str],
        progress: Callable[[str], None] | None = None,
        reference_paths: list[Path] | None = None,
        mode: str = "generate",
        source_image_path: Path | None = None,
    ) -> dict[str, Any]:
        """Return real OCR and multimodal evidence in Azure mode, deterministic evidence locally."""
        if self.mode != "azure":
            if progress:
                progress("ocr_output")
            return {
                "provider": "text-layer",
                "ocr_lines": [{"text": "\n".join(value for value in (title, body, *(feature_text or [])) if value), "bbox": bbox}],
                "text_review": self.review_known_text(
                    title=title,
                    body=body,
                    feature_text=feature_text,
                    bbox=bbox,
                    number_allowlist=number_allowlist,
                ),
                "llm_review": {},
            }

        ocr_errors: list[str] = []
        if progress:
            progress("ocr_output")
        try:
            generated_lines = self._read_image_text(
                output_path,
                token_provider=self._vision_token_provider,
            )
        except self._azure_vision_ocr_error as exc:
            ocr_errors.append(str(exc))
            generated_lines = [
                self._ocr_line(
                    text="\n".join(value for value in (title, body, *(feature_text or [])) if value),
                    confidence=1.0,
                    bbox=bbox,
                )
            ]
        reference_lines = []
        all_reference_paths = list(dict.fromkeys([
            *(reference_paths or []),
            *([reference_path] if reference_path else []),
        ]))
        if reference_path:
            if progress:
                progress("ocr_reference")
            try:
                reference_lines = self._read_image_text(
                    reference_path,
                    token_provider=self._vision_token_provider,
                )
            except self._azure_vision_ocr_error as exc:
                ocr_errors.append(str(exc))
        text_review = self._review_text_ocr(
            generated_lines,
            self._text_spec(
                required_text=[value for value in (title.strip(), body.strip(), *(feature_text or [])) if value],
                number_allowlist=number_allowlist,
                strict_number_allowlist=True,
                expected_text_region=bbox,
                image_path=str(output_path),
            ),
        ).to_dict()
        generated_ocr = self._ocr_dicts(generated_lines)
        reference_ocr = self._ocr_dicts(reference_lines)
        if progress:
            progress("llm_review")
        try:
            llm_review = self._review_image_with_llm(
                self._review_evidence(
                    mode=mode,
                    user_prompt=prompt,
                    generated_image_path=str(output_path),
                    reference_image_path=str(source_image_path or ""),
                    product_reference_image_path=str(reference_path or ""),
                    product_reference_image_paths=[str(path) for path in all_reference_paths],
                    generated_ocr_lines=generated_ocr,
                    reference_ocr_lines=reference_ocr,
                    visual_review=visual_review,
                    generation=generation,
                    review_plan=review_plan,
                ),
                timeout=self._positive_int_env("PCP_LLM_REVIEW_TIMEOUT", 120),
                max_attempts=self._positive_int_env("PCP_LLM_REVIEW_MAX_ATTEMPTS", 3),
                token_provider=self._openai_token_provider,
            ).to_dict()
        except self._llm_reviewer_error as exc:
            llm_review = {
                "status": "review",
                "summary": "LLM 审查暂时不可用，图片已保留并转为人工审核。",
                "issues": [
                    {
                        "code": "review_unavailable",
                        "severity": "P2",
                        "message": "LLM 审查连接失败，请人工确认图片质量。",
                    }
                ],
                "error": str(exc),
                "degraded": True,
            }
        if ocr_errors:
            llm_review = dict(llm_review)
            llm_review["status"] = (
                "fail" if llm_review.get("status") == "fail" else "review"
            )
            llm_review["degraded"] = True
            llm_review["ocr_error"] = "; ".join(dict.fromkeys(ocr_errors))
            llm_review["issues"] = [
                {
                    "code": "ocr_unavailable",
                    "severity": "P2",
                    "message": "Azure OCR 暂时不可用，已使用本地文字层校验，请人工确认。",
                },
                *list(llm_review.get("issues", [])),
            ]
        return {
            "provider": (
                "text-layer-fallback+azure-openai"
                if ocr_errors
                else "azure-ai-vision+azure-openai"
            ),
            "ocr_lines": generated_ocr,
            "reference_ocr_lines": reference_ocr,
            "text_review": text_review,
            "llm_review": llm_review,
        }

    def rank(self, rows: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
        payloads: list[dict[str, Any]] = []
        for row in rows:
            status = row["qa_status"]
            issues = row["issues"]
            severity_penalty = sum(18 if item.get("severity") == "P0" else 10 if item.get("severity") == "P1" else 4 for item in issues)
            breakdown = {
                "text_accuracy": max(0, 100 - severity_penalty),
                "product_consistency": 96 if row["evidence"]["reference_consistency"]["reference_count"] else 74,
                "layout_stability": max(0, 100 - severity_penalty),
                "brand_compliance": max(0, 98 - severity_penalty),
            }
            review_payload = {"status": status, "confidence": .98, "score_breakdown": breakdown}
            payloads.append(
                {
                    "candidate_index": row["candidate_index"],
                    "result": review_payload,
                    "llm_review": {"confidence": .98},
                    "score": self._score_candidate(review_payload),
                }
            )
        ranked = self._rank_candidates(payloads)
        return {int(row["candidate_index"]): row for row in ranked}

    def repair_prompt(self, original_prompt: str, suggested_fix: str, title: str, body: str) -> str:
        return self._compose_repair_prompt(
            original_prompt,
            suggested_fix,
            {
                "must_appear": [],
                "must_not_appear": ["预留区域中的任何文字、字母、数字、Logo、水印、文本框或占位符", "画面新增文字"],
                "must_preserve": ["商品结构", "商品本体已有品牌标识和物理面板信息", "预留文字区域"],
            },
        )

    @staticmethod
    def _ocr_dicts(lines: list[Any]) -> list[dict[str, Any]]:
        return [
            {"text": line.text, "confidence": line.confidence, "bbox": line.bbox}
            for line in lines
        ]

    @staticmethod
    def _bbox_center_inside(
        value: Any,
        outer: tuple[float, float, float, float],
    ) -> bool:
        if not isinstance(value, (list, tuple)) or len(value) != 4:
            return False
        try:
            center_x = (float(value[0]) + float(value[2])) / 2
            center_y = (float(value[1]) + float(value[3])) / 2
        except (TypeError, ValueError):
            return False
        return outer[0] <= center_x <= outer[2] and outer[1] <= center_y <= outer[3]

    @staticmethod
    def _positive_int_env(name: str, default: int) -> int:
        try:
            return max(1, int(os.environ.get(name, str(default))))
        except ValueError:
            return default
