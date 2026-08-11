from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image, ImageOps

from product_content_platform.adapters.layout_catalog import LayoutContentCatalog
from product_content_platform.adapters.production_engine import LocalProductionEngine
from product_content_platform.domain import PageItem, PageType


SHOWCASES = (
    {
        "slug": "square-2048",
        "size": (2048, 2048),
        "template_id": "scene-overlay",
        "page_type": PageType.SCENE,
        "title": "静谧洗护，自成风景",
        "body": "自然光、温润木饰面与石材地面，共同构成真实而高级的家庭洗护空间。",
    },
    {
        "slug": "landscape-3840",
        "size": (3840, 2160),
        "template_id": "landscape-story-left-v1",
        "page_type": PageType.HERO,
        "title": "横向延展，静谧洗护",
        "body": "晨光、石材与木饰面，共同构成宽银幕生活叙事。",
    },
    {
        "slug": "portrait-3840",
        "size": (2160, 3840),
        "template_id": "portrait-story-top-v1",
        "page_type": PageType.HERO,
        "title": "向上生长的洗护空间",
        "body": "天光倾落，让专业护理成为家的安静一景。",
    },
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build deterministic showcase assets from approved sources.")
    parser.add_argument("--square-source", type=Path, required=True)
    parser.add_argument("--landscape-source", type=Path, required=True)
    parser.add_argument("--portrait-source", type=Path, required=True)
    parser.add_argument("--product-reference", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("examples/showcases"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    sources = {
        "square-2048": args.square_source,
        "landscape-3840": args.landscape_source,
        "portrait-3840": args.portrait_source,
    }
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    shutil.copy2(args.product_reference, output / "product-reference.jpg")

    with TemporaryDirectory(prefix="pcp-showcase-") as temp_dir:
        temp = Path(temp_dir)
        catalog = LayoutContentCatalog(temp / "templates.json")
        engine = LocalProductionEngine(temp / "production", generator=None, template_resolver=catalog.template)  # type: ignore[arg-type]
        for index, showcase in enumerate(SHOWCASES, start=1):
            source = sources[str(showcase["slug"])]
            target_size = tuple(showcase["size"])
            base_path = output / f"{showcase['slug']}-base.png"
            text_path = output / f"{showcase['slug']}-text.png"
            output_path = output / f"{showcase['slug']}.png"
            with Image.open(source) as image:
                resized = ImageOps.fit(image.convert("RGB"), target_size, method=Image.Resampling.LANCZOS)
                resized.save(base_path, format="PNG", optimize=True)
            page = PageItem(
                id=f"showcase-page-{index}",
                order=1,
                page_type=showcase["page_type"],
                title=str(showcase["title"]),
                body=str(showcase["body"]),
                visual_goal="内置版式库验收示例",
                template_id=str(showcase["template_id"]),
                heading_level=1,
            )
            engine._compose(
                base_path=base_path,
                text_path=text_path,
                output_path=output_path,
                page=page,
                product_bbox=(0, 0, target_size[0], target_size[1]),
                typography={"title_color": "#1f3027", "body_color": "#42564a"},
            )
            print(f"built {output_path} ({target_size[0]}x{target_size[1]})")


if __name__ == "__main__":
    main()
