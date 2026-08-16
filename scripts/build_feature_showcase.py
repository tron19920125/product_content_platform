from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from product_content_platform.adapters.base_image_generation import LocalBaseImageGenerator
from product_content_platform.adapters.production_engine import LocalProductionEngine
from product_content_platform.domain import FeaturePoint, PageItem, PageStatus, PageType


ROOT = Path(__file__).resolve().parents[1]
SHOWCASE_ROOT = ROOT / "examples" / "showcases"
SLUG = "landscape-feature-3840"


def main() -> None:
    source_base = SHOWCASE_ROOT / "landscape-3840-base.png"
    if not source_base.is_file():
        raise FileNotFoundError(source_base)
    template = {
        "id": "landscape-feature-band-v1",
        "size": "3840x2160",
        "text_box": [.08, .08, .52, .36],
        "title_box": [.08, .08, .52, .20],
        "body_box": [.08, .22, .43, .36],
        "product_box": [.47, .24, .96, .94],
        "product_anchor_box": [.58, .34, .90, .92],
        "feature_slots": [{
            "id": "feature-band", "name": "三项核心卖点", "box": [.05, .46, .34, .82],
            "layout": "row", "columns": 3, "min_items": 3, "max_items": 3,
            "icon_position": "top", "icon_scale": .30, "item_gap": .012,
            "icon_text_gap": .012,
            "card_style": {"background_color": "#F7F3EA", "background_opacity": .72, "radius": .08},
            "title_style": {"font_family": "noto-sans-sc", "font_weight": 700, "font_size": 64, "color": "#244A3A"},
            "description_style": {"font_family": "noto-sans-sc", "font_weight": 400, "font_size": 40, "color": "#52665C"},
        }],
    }
    page = PageItem(
        id="showcase-landscape-feature-3840-page-1", order=1,
        page_type=PageType.FUNCTION, title="三重智护，洁净有序",
        body="从深层洁净到轻柔呵护，让每一次洗护更从容。",
        visual_goal="横版高端洗护功能页：左侧图文卖点，右侧真实商品空间。",
        template_id="landscape-feature-band-v1", status=PageStatus.READY,
        feature_points=(
            FeaturePoint("deep-clean", "深层洁净", "减少顽固残留", "洁净闪光", ("selling_point:深层洁净",)),
            FeaturePoint("gentle-care", "轻柔呵护", "保护衣物纤维", "保护盾牌", ("selling_point:轻柔呵护",)),
            FeaturePoint("quiet-energy", "安静节能", "高效融入日常", "节能叶片", ("selling_point:安静节能",)),
        ),
    )
    with tempfile.TemporaryDirectory(prefix="pcp-feature-showcase-") as directory:
        work = Path(directory)
        base_path = work / "base.png"
        shutil.copy2(source_base, base_path)
        engine = LocalProductionEngine(
            work, LocalBaseImageGenerator(), template_resolver=lambda _template_id: template,
            font_resolver=_font_resolver,
        )
        document = engine._build_text_document(
            candidate_id="showcase-landscape-feature-3840-candidate-1",
            base_path=base_path, page=page, instruction="极简高级、结构清晰",
        )
        prepared, icon_generation = engine._prepare_feature_icons(document=document, output_root=work / "candidate")
        composition = engine._compose_text_document(
            base_path=base_path, text_path=work / "candidate" / "text_layer.png",
            output_path=work / "candidate" / "composed.png", document=prepared,
            product_bbox=(2227, 734, 3456, 1987),
        )
        composition["icon_generation"] = icon_generation
        shutil.copy2(base_path, SHOWCASE_ROOT / f"{SLUG}-base.png")
        shutil.copy2(work / "candidate" / "text_layer.png", SHOWCASE_ROOT / f"{SLUG}-text.png")
        shutil.copy2(work / "candidate" / "icon_layer.png", SHOWCASE_ROOT / f"{SLUG}-icon.png")
        shutil.copy2(work / "candidate" / "composed.png", SHOWCASE_ROOT / f"{SLUG}.png")
        icon_destination = SHOWCASE_ROOT / f"{SLUG}-icons"
        icon_destination.mkdir(parents=True, exist_ok=True)
        for item in prepared.feature_groups[0].items:
            shutil.copy2(engine.resolve(item.icon_path), icon_destination / Path(item.icon_path).name)
        pack_path = str(icon_generation.get("pack_path") or "")
        if pack_path:
            shutil.copy2(engine.resolve(pack_path), icon_destination / "icon_pack.png")
        _rewrite_paths(composition)
        (SHOWCASE_ROOT / f"{SLUG}-metadata.json").write_text(
            json.dumps(composition, ensure_ascii=False, indent=2), encoding="utf-8",
        )


def _rewrite_paths(composition: dict) -> None:
    composition["icon_layer_path"] = "icon_layer.png"
    for group in composition.get("feature_groups") or []:
        for item in group.get("items") or []:
            item["icon_path"] = f"icons/{Path(str(item.get('icon_path') or '')).name}"
    generation = composition.get("icon_generation") or {}
    generation["pack_path"] = "icons/icon_pack.png"
    for item in generation.get("icons") or []:
        item["path"] = f"icons/{Path(str(item.get('path') or '')).name}"


def _font_resolver(family: str) -> Path | None:
    fonts = ROOT / "frontend" / "public" / "fonts"
    mapping = {
        "noto-sans-sc": fonts / "NotoSansSC-Variable.ttf",
        "noto-serif-sc": fonts / "NotoSerifSC-Variable.ttf",
    }
    path = mapping.get(family)
    return path if path and path.is_file() else None


if __name__ == "__main__":
    main()
