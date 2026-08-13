from __future__ import annotations

import os
import re
import urllib.request
import zipfile
from pathlib import Path
from typing import Any


_FONT_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "id": "noto-sans-sc", "name": "Noto Sans SC", "display_name": "思源黑体（Noto）",
        "category": "现代黑体", "weights": [100, 200, 300, 400, 500, 600, 700, 800, 900],
        "preview": "品质生活，自有分寸", "license": "OFL-1.1",
        "license_url": "https://github.com/google/fonts/blob/main/ofl/notosanssc/OFL.txt",
        "source_url": "https://raw.githubusercontent.com/google/fonts/main/ofl/notosanssc/NotoSansSC%5Bwght%5D.ttf",
        "file_name": "NotoSansSC-Variable.ttf", "commercial_use": True, "coverage": "完整简体中文",
    },
    {
        "id": "noto-serif-sc", "name": "Noto Serif SC", "display_name": "思源宋体（Noto）",
        "category": "宋体衬线", "weights": [200, 300, 400, 500, 600, 700, 800, 900],
        "preview": "经典质感，历久弥新", "license": "OFL-1.1",
        "license_url": "https://github.com/google/fonts/blob/main/ofl/notoserifsc/OFL.txt",
        "source_url": "https://raw.githubusercontent.com/google/fonts/main/ofl/notoserifsc/NotoSerifSC%5Bwght%5D.ttf",
        "file_name": "NotoSerifSC-Variable.ttf", "commercial_use": True, "coverage": "完整简体中文",
    },
    {
        "id": "lxgw-wenkai", "name": "LXGW WenKai", "display_name": "霞鹜文楷",
        "category": "文楷", "weights": [300, 400, 700], "preview": "把日常写成生活美学",
        "license": "OFL-1.1", "license_url": "https://github.com/lxgw/LxgwWenKai/blob/main/OFL.txt",
        "source_url": "https://raw.githubusercontent.com/lxgw/LxgwWenKai/main/fonts/TTF/LXGWWenKai-Regular.ttf",
        "file_name": "LXGWWenKai-Regular.ttf", "commercial_use": True, "coverage": "完整简体中文",
    },
    {
        "id": "ma-shan-zheng", "name": "Ma Shan Zheng", "display_name": "马善政毛笔体",
        "category": "书法", "weights": [400], "preview": "东方风韵，自在挥洒", "license": "OFL-1.1",
        "license_url": "https://github.com/google/fonts/blob/main/ofl/mashanzheng/OFL.txt",
        "source_url": "https://raw.githubusercontent.com/google/fonts/main/ofl/mashanzheng/MaShanZheng-Regular.ttf",
        "file_name": "MaShanZheng-Regular.ttf", "commercial_use": True, "coverage": "常用简体中文",
    },
    {
        "id": "long-cang", "name": "Long Cang", "display_name": "龙藏体",
        "category": "手写", "weights": [400], "preview": "灵感落笔，松弛有度", "license": "OFL-1.1",
        "license_url": "https://github.com/google/fonts/blob/main/ofl/longcang/OFL.txt",
        "source_url": "https://raw.githubusercontent.com/google/fonts/main/ofl/longcang/LongCang-Regular.ttf",
        "file_name": "LongCang-Regular.ttf", "commercial_use": True, "coverage": "常用简体中文",
    },
    {
        "id": "liu-jian-mao-cao", "name": "Liu Jian Mao Cao", "display_name": "刘建毛草",
        "category": "草书", "weights": [400], "preview": "新意登场，一笔成风", "license": "OFL-1.1",
        "license_url": "https://github.com/google/fonts/blob/main/ofl/liujianmaocao/OFL.txt",
        "source_url": "https://raw.githubusercontent.com/google/fonts/main/ofl/liujianmaocao/LiuJianMaoCao-Regular.ttf",
        "file_name": "LiuJianMaoCao-Regular.ttf", "commercial_use": True, "coverage": "常用简体中文",
    },
    {
        "id": "zhi-mang-xing", "name": "Zhi Mang Xing", "display_name": "志莽行书",
        "category": "行书", "weights": [400], "preview": "率性表达，恰到好处", "license": "OFL-1.1",
        "license_url": "https://github.com/google/fonts/blob/main/ofl/zhimangxing/OFL.txt",
        "source_url": "https://raw.githubusercontent.com/google/fonts/main/ofl/zhimangxing/ZhiMangXing-Regular.ttf",
        "file_name": "ZhiMangXing-Regular.ttf", "commercial_use": True, "coverage": "常用简体中文",
    },
    {
        "id": "smiley-sans", "name": "Smiley Sans", "display_name": "得意黑",
        "category": "艺术标题", "weights": [400], "preview": "新品大赏，锋芒正好", "license": "OFL-1.1",
        "license_url": "https://github.com/atelier-anchor/smiley-sans/blob/main/LICENSE",
        "source_url": "https://github.com/atelier-anchor/smiley-sans/releases/download/v2.0.1/smiley-sans-v2.0.1.zip",
        "archive_member": "SmileySans-Oblique.ttf",
        "file_name": "SmileySans-Oblique.ttf", "commercial_use": True, "coverage": "常用简体中文",
    },
    {
        "id": "zcool-kuaile", "name": "ZCOOL KuaiLe", "display_name": "站酷快乐体",
        "category": "活力标题", "weights": [400], "preview": "快乐上新，好物登场", "license": "OFL-1.1",
        "license_url": "https://github.com/google/fonts/blob/main/ofl/zcoolkuaile/OFL.txt",
        "source_url": "https://raw.githubusercontent.com/google/fonts/main/ofl/zcoolkuaile/ZCOOLKuaiLe-Regular.ttf",
        "file_name": "ZCOOLKuaiLe-Regular.ttf", "commercial_use": True, "coverage": "常用简体中文",
    },
    {
        "id": "zcool-qingke-huangyou", "name": "ZCOOL QingKe HuangYou", "display_name": "站酷庆科黄油体",
        "category": "几何标题", "weights": [400], "preview": "轻盈设计，刚好出彩", "license": "OFL-1.1",
        "license_url": "https://github.com/google/fonts/blob/main/ofl/zcoolqingkehuangyou/OFL.txt",
        "source_url": "https://raw.githubusercontent.com/google/fonts/main/ofl/zcoolqingkehuangyou/ZCOOLQingKeHuangYou-Regular.ttf",
        "file_name": "ZCOOLQingKeHuangYou-Regular.ttf", "commercial_use": True, "coverage": "常用简体中文",
    },
    {
        "id": "zcool-xiaowei", "name": "ZCOOL XiaoWei", "display_name": "站酷小薇体",
        "category": "文艺衬线", "weights": [400], "preview": "细品生活，自有余韵", "license": "OFL-1.1",
        "license_url": "https://github.com/google/fonts/blob/main/ofl/zcoolxiaowei/OFL.txt",
        "source_url": "https://raw.githubusercontent.com/google/fonts/main/ofl/zcoolxiaowei/ZCOOLXiaoWei-Regular.ttf",
        "file_name": "ZCOOLXiaoWei-Regular.ttf", "commercial_use": True, "coverage": "常用简体中文",
    },
)


_BUNDLED_FONT_IDS = {
    "ma-shan-zheng", "long-cang", "liu-jian-mao-cao", "zhi-mang-xing",
    "smiley-sans", "zcool-kuaile", "zcool-qingke-huangyou", "zcool-xiaowei",
}


class FontCatalog:
    """Curated commercial-use font registry shared by web previews and server rendering."""

    def __init__(self, root: Path, bundled_root: Path | None = None) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.bundled_root = bundled_root.resolve() if bundled_root else None
        self._definitions = {item["id"]: dict(item) for item in _FONT_DEFINITIONS}

    def list(self) -> list[dict[str, Any]]:
        return [self._public(item) for item in self._definitions.values()]

    def get(self, font_id: str) -> dict[str, Any]:
        clean = re.sub(r"[^a-z0-9-]", "", font_id.lower())
        item = self._definitions.get(clean)
        if item is None:
            raise KeyError(font_id)
        return self._public(item)

    def path(self, font_id: str, *, download: bool = True) -> Path | None:
        item = self._definitions.get(font_id)
        if item is None:
            return self.system_fallback(font_id)
        bundled = self._bundled_path(item)
        if bundled is not None:
            return bundled
        path = self.root / item["file_name"]
        if path.exists() and 16_000 <= path.stat().st_size <= 40_000_000:
            return path
        if not download or os.environ.get("PCP_FONT_DOWNLOAD", "1").strip().lower() in {"0", "false", "no"}:
            return None
        temporary = path.with_suffix(path.suffix + ".download")
        try:
            request = urllib.request.Request(item["source_url"], headers={"User-Agent": "product-content-platform/0.1"})
            download = temporary.with_suffix(temporary.suffix + ".source") if item.get("archive_member") else temporary
            with urllib.request.urlopen(request, timeout=45) as response, download.open("wb") as target:
                total = 0
                while chunk := response.read(256 * 1024):
                    total += len(chunk)
                    if total > 40_000_000:
                        raise ValueError("font file exceeds 40MB")
                    target.write(chunk)
            if item.get("archive_member"):
                with zipfile.ZipFile(download) as archive:
                    match = next((name for name in archive.namelist() if name.endswith(str(item["archive_member"]))), "")
                    if not match:
                        raise ValueError("font archive member is missing")
                    with archive.open(match) as source, temporary.open("wb") as target:
                        while chunk := source.read(256 * 1024):
                            target.write(chunk)
                download.unlink(missing_ok=True)
                total = temporary.stat().st_size
            if total < 16_000:
                raise ValueError("font file is incomplete")
            temporary.replace(path)
            return path
        except Exception:
            temporary.unlink(missing_ok=True)
            temporary.with_suffix(temporary.suffix + ".source").unlink(missing_ok=True)
            return None

    @staticmethod
    def system_fallback(font_id: str = "system_sans") -> Path | None:
        windows = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        families = {
            "system_serif": [windows / "simsun.ttc", Path("/System/Library/Fonts/Supplemental/Songti.ttc")],
            "system_bold": [windows / "msyhbd.ttc", windows / "simhei.ttf", Path("/System/Library/Fonts/PingFang.ttc")],
            "system_sans": [windows / "msyh.ttc", windows / "Deng.ttf", Path("/System/Library/Fonts/PingFang.ttc")],
        }
        candidates = families.get(font_id, families["system_sans"])
        return next((path for path in candidates if path.exists()), None)

    def _public(self, item: dict[str, Any]) -> dict[str, Any]:
        path = self.root / item["file_name"]
        bundled = self._bundled_path(item)
        available = bundled is not None or (path.exists() and path.stat().st_size >= 16_000)
        return {
            **{key: value for key, value in item.items() if key not in {"source_url", "archive_member"}},
            "installed": available,
            "preview_available": available,
            "content_url": f"/api/fonts/{item['id']}/content",
        }

    def _bundled_path(self, item: dict[str, Any]) -> Path | None:
        if self.bundled_root is None or item["id"] not in _BUNDLED_FONT_IDS:
            return None
        path = self.bundled_root / item["file_name"]
        return path if path.exists() and 16_000 <= path.stat().st_size <= 40_000_000 else None
