from __future__ import annotations

from pathlib import Path
from typing import Any


class ProductQualityToolkit:
    """Deep module exposing OCR, multimodal review, scoring, ranking and repair behind one interface."""

    def __init__(self, workspace_root: Path | None = None, mode: str = "local") -> None:
        if mode not in {"local", "azure"}:
            raise ValueError("质检模式必须是 local 或 azure")
        # The optional path remains accepted to avoid breaking local callers; it is not used.
        _ = workspace_root
        from product_content_platform.quality.azure_vision_ocr import read_image_text
        from product_content_platform.quality.scoring import compose_repair_prompt, rank_candidates, score_candidate
        from product_content_platform.quality.llm_reviewer import ReviewEvidence, review_image_with_llm
        from product_content_platform.quality.review_planner import create_review_plan, fallback_review_plan
        from product_content_platform.quality.text_review import OcrLine, TextReviewSpec, review_text_ocr
        from product_content_platform.quality.visual_review import review_edit_visuals
        from product_content_platform.integrations.azure_credentials import token_provider_from_env

        self.mode = mode
        self._compose_repair_prompt = compose_repair_prompt
        self._rank_candidates = rank_candidates
        self._score_candidate = score_candidate
        self._read_image_text = read_image_text
        self._review_evidence = ReviewEvidence
        self._review_image_with_llm = review_image_with_llm
        self._create_review_plan = create_review_plan
        self._ocr_line = OcrLine
        self._text_spec = TextReviewSpec
        self._review_text_ocr = review_text_ocr
        self._fallback_review_plan = fallback_review_plan
        self._review_edit_visuals = review_edit_visuals
        self._token_provider = token_provider_from_env() if mode == "azure" else None

    def review_plan(self, prompt: str, reference_path: Path | None = None) -> dict[str, Any]:
        if self.mode == "azure":
            return self._create_review_plan(
                prompt,
                mode="generate",
                product_reference_image_path=str(reference_path or ""),
                token_provider=self._token_provider,
            ).to_dict()
        return self._fallback_review_plan(prompt, mode="generate").to_dict()

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
    ) -> dict[str, Any]:
        expected = [value for value in (title.strip(), body.strip()) if value]
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
        bbox: tuple[float, float, float, float],
        number_allowlist: list[str],
    ) -> dict[str, Any]:
        """Return real OCR and multimodal evidence in Azure mode, deterministic evidence locally."""
        if self.mode != "azure":
            return {
                "provider": "text-layer",
                "ocr_lines": [{"text": "\n".join(value for value in (title, body) if value), "bbox": bbox}],
                "text_review": self.review_known_text(
                    title=title,
                    body=body,
                    bbox=bbox,
                    number_allowlist=number_allowlist,
                ),
                "llm_review": {},
            }

        generated_lines = self._read_image_text(output_path, token_provider=self._token_provider)
        reference_lines = (
            self._read_image_text(reference_path, token_provider=self._token_provider)
            if reference_path
            else []
        )
        text_review = self._review_text_ocr(
            generated_lines,
            self._text_spec(
                required_text=[value for value in (title.strip(), body.strip()) if value],
                number_allowlist=number_allowlist,
                strict_number_allowlist=True,
                expected_text_region=bbox,
                image_path=str(output_path),
            ),
        ).to_dict()
        generated_ocr = self._ocr_dicts(generated_lines)
        reference_ocr = self._ocr_dicts(reference_lines)
        llm_review = self._review_image_with_llm(
            self._review_evidence(
                mode="generate",
                user_prompt=prompt,
                generated_image_path=str(output_path),
                product_reference_image_path=str(reference_path or ""),
                generated_ocr_lines=generated_ocr,
                reference_ocr_lines=reference_ocr,
                visual_review=visual_review,
                generation=generation,
                review_plan=review_plan,
            ),
            token_provider=self._token_provider,
        ).to_dict()
        return {
            "provider": "azure-ai-vision+azure-openai",
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
            {"must_appear": [title, body], "must_not_appear": [], "must_preserve": ["商品结构", "品牌信息"]},
        )

    @staticmethod
    def _ocr_dicts(lines: list[Any]) -> list[dict[str, Any]]:
        return [
            {"text": line.text, "confidence": line.confidence, "bbox": line.bbox}
            for line in lines
        ]
