from __future__ import annotations

from typing import Any


class FixedContentCatalog:
    """P0 catalog kept behind one seam so database-backed management can replace it later."""

    def templates(self) -> list[dict[str, Any]]:
        return [
            {"id": "hero-center", "name": "主视觉居中", "page_types": ["hero"], "layout": "center", "safe_area": 0.08},
            {"id": "split-left", "name": "左文右图", "page_types": ["selling_point", "function"], "layout": "split_left", "safe_area": 0.07},
            {"id": "split-right", "name": "左图右文", "page_types": ["selling_point", "function"], "layout": "split_right", "safe_area": 0.07},
            {"id": "scene-overlay", "name": "场景叠字", "page_types": ["scene"], "layout": "overlay", "safe_area": 0.1},
            {"id": "data-grid", "name": "参数信息", "page_types": ["parameters"], "layout": "grid", "safe_area": 0.08},
        ]

    def recipes(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "commerce-detail-v1",
                "name": "家电电商详情基础配方",
                "status": "published",
                "version": 1,
                "page_types": ["hero", "selling_point", "function", "scene", "parameters"],
                "candidate_count": 2,
                "qa_policy": "commerce-basic-v1",
            }
        ]
