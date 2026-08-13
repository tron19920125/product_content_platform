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
        "tags": ["正文", "现代", "通用"],
    },
    {
        "id": "noto-serif-sc", "name": "Noto Serif SC", "display_name": "思源宋体（Noto）",
        "category": "宋体衬线", "weights": [200, 300, 400, 500, 600, 700, 800, 900],
        "preview": "经典质感，历久弥新", "license": "OFL-1.1",
        "license_url": "https://github.com/google/fonts/blob/main/ofl/notoserifsc/OFL.txt",
        "source_url": "https://raw.githubusercontent.com/google/fonts/main/ofl/notoserifsc/NotoSerifSC%5Bwght%5D.ttf",
        "file_name": "NotoSerifSC-Variable.ttf", "commercial_use": True, "coverage": "完整简体中文",
        "tags": ["正文", "质感", "通用"],
    },
    {
        "id": "lxgw-wenkai", "name": "LXGW WenKai", "display_name": "霞鹜文楷",
        "category": "文楷", "weights": [300, 400, 700], "preview": "把日常写成生活美学",
        "license": "OFL-1.1", "license_url": "https://github.com/lxgw/LxgwWenKai/blob/main/OFL.txt",
        "source_url": "https://raw.githubusercontent.com/lxgw/LxgwWenKai/main/fonts/TTF/LXGWWenKai-Regular.ttf",
        "file_name": "LXGWWenKai-Regular.ttf", "commercial_use": True, "coverage": "完整简体中文",
        "tags": ["文艺", "生活方式", "正文"],
    },
    {
        "id": "ma-shan-zheng", "name": "Ma Shan Zheng", "display_name": "马善政毛笔体",
        "category": "书法", "weights": [400], "preview": "东方风韵，自在挥洒", "license": "OFL-1.1",
        "license_url": "https://github.com/google/fonts/blob/main/ofl/mashanzheng/OFL.txt",
        "source_url": "https://raw.githubusercontent.com/google/fonts/main/ofl/mashanzheng/MaShanZheng-Regular.ttf",
        "file_name": "MaShanZheng-Regular.ttf", "commercial_use": True, "coverage": "常用简体中文",
        "tags": ["国风", "毛笔", "标题"],
    },
    {
        "id": "long-cang", "name": "Long Cang", "display_name": "龙藏体",
        "category": "手写", "weights": [400], "preview": "灵感落笔，松弛有度", "license": "OFL-1.1",
        "license_url": "https://github.com/google/fonts/blob/main/ofl/longcang/OFL.txt",
        "source_url": "https://raw.githubusercontent.com/google/fonts/main/ofl/longcang/LongCang-Regular.ttf",
        "file_name": "LongCang-Regular.ttf", "commercial_use": True, "coverage": "常用简体中文",
        "tags": ["手写", "自然", "标题"],
    },
    {
        "id": "liu-jian-mao-cao", "name": "Liu Jian Mao Cao", "display_name": "刘建毛草",
        "category": "草书", "weights": [400], "preview": "新意登场，一笔成风", "license": "OFL-1.1",
        "license_url": "https://github.com/google/fonts/blob/main/ofl/liujianmaocao/OFL.txt",
        "source_url": "https://raw.githubusercontent.com/google/fonts/main/ofl/liujianmaocao/LiuJianMaoCao-Regular.ttf",
        "file_name": "LiuJianMaoCao-Regular.ttf", "commercial_use": True, "coverage": "常用简体中文",
        "tags": ["国风", "草书", "标题"],
    },
    {
        "id": "zhi-mang-xing", "name": "Zhi Mang Xing", "display_name": "志莽行书",
        "category": "行书", "weights": [400], "preview": "率性表达，恰到好处", "license": "OFL-1.1",
        "license_url": "https://github.com/google/fonts/blob/main/ofl/zhimangxing/OFL.txt",
        "source_url": "https://raw.githubusercontent.com/google/fonts/main/ofl/zhimangxing/ZhiMangXing-Regular.ttf",
        "file_name": "ZhiMangXing-Regular.ttf", "commercial_use": True, "coverage": "常用简体中文",
        "tags": ["行书", "率性", "标题"],
    },
    {
        "id": "smiley-sans", "name": "Smiley Sans", "display_name": "得意黑",
        "category": "艺术标题", "weights": [400], "preview": "新品大赏，锋芒正好", "license": "OFL-1.1",
        "license_url": "https://github.com/atelier-anchor/smiley-sans/blob/main/LICENSE",
        "source_url": "https://github.com/atelier-anchor/smiley-sans/releases/download/v2.0.1/smiley-sans-v2.0.1.zip",
        "archive_member": "SmileySans-Oblique.ttf",
        "file_name": "SmileySans-Oblique.ttf", "commercial_use": True, "coverage": "常用简体中文",
        "tags": ["促销", "潮流", "标题"],
    },
    {
        "id": "lxgw-marker-gothic", "name": "LXGW Marker Gothic", "display_name": "霞鹜漫黑",
        "category": "马克笔标题", "weights": [400], "preview": "灵感上新，醒目开场", "license": "OFL-1.1",
        "license_url": "https://github.com/lxgw/LxgwMarkerGothic/blob/main/OFL.txt",
        "source_url": "https://raw.githubusercontent.com/lxgw/LxgwMarkerGothic/main/fonts/ttf/LXGWMarkerGothic-Regular.ttf",
        "file_name": "LXGWMarkerGothic-Regular.ttf", "commercial_use": True, "coverage": "完整简繁中文",
        "tags": ["促销", "广告", "标题"],
    },
    {
        "id": "iansui", "name": "Iansui", "display_name": "芫荽",
        "category": "自然手写", "weights": [400], "preview": "轻松表达，自然有趣", "license": "OFL-1.1",
        "license_url": "https://github.com/google/fonts/blob/main/ofl/iansui/OFL.txt",
        "source_url": "https://raw.githubusercontent.com/google/fonts/main/ofl/iansui/Iansui-Regular.ttf",
        "file_name": "Iansui-Regular.ttf", "commercial_use": True, "coverage": "简繁中文常用字",
        "tags": ["手写", "亲和", "生活方式"],
    },
    {
        "id": "wd-xl-lubrifont", "name": "WD-XL Lubrifont SC", "display_name": "润植家如印奏章楷",
        "category": "圆润展示", "weights": [400], "preview": "圆润上新，亲和醒目", "license": "OFL-1.1",
        "license_url": "https://github.com/google/fonts/blob/main/ofl/wdxllubrifontsc/OFL.txt",
        "source_url": "https://raw.githubusercontent.com/google/fonts/main/ofl/wdxllubrifontsc/WDXLLubrifontSC-Regular.ttf",
        "file_name": "WDXLLubrifontSC-Regular.ttf", "commercial_use": True, "coverage": "完整简体中文",
        "tags": ["促销", "圆体", "标题"],
    },
    {
        "id": "bebas-neue", "name": "Bebas Neue", "display_name": "Bebas Neue",
        "category": "数字价格", "weights": [400], "preview": "NEW 2026 · ¥299", "license": "OFL-1.1",
        "license_url": "https://github.com/google/fonts/blob/main/ofl/bebasneue/OFL.txt",
        "source_url": "https://raw.githubusercontent.com/google/fonts/main/ofl/bebasneue/BebasNeue-Regular.ttf",
        "file_name": "BebasNeue-Regular.ttf", "commercial_use": True, "coverage": "拉丁字母与数字",
        "tags": ["价格", "数字", "促销"],
    },
    {
        "id": "anton", "name": "Anton", "display_name": "Anton",
        "category": "英文标题", "weights": [400], "preview": "SUPER SALE 50%", "license": "OFL-1.1",
        "license_url": "https://github.com/google/fonts/blob/main/ofl/anton/OFL.txt",
        "source_url": "https://raw.githubusercontent.com/google/fonts/main/ofl/anton/Anton-Regular.ttf",
        "file_name": "Anton-Regular.ttf", "commercial_use": True, "coverage": "拉丁字母与数字",
        "tags": ["英文", "促销", "粗标题"],
    },
    {
        "id": "bungee", "name": "Bungee", "display_name": "Bungee",
        "category": "潮流展示", "weights": [400], "preview": "DROP 08 · GO!", "license": "OFL-1.1",
        "license_url": "https://github.com/google/fonts/blob/main/ofl/bungee/OFL.txt",
        "source_url": "https://raw.githubusercontent.com/google/fonts/main/ofl/bungee/Bungee-Regular.ttf",
        "file_name": "Bungee-Regular.ttf", "commercial_use": True, "coverage": "拉丁字母与数字",
        "tags": ["潮流", "英文", "标题"],
    },
    {
        "id": "black-ops-one", "name": "Black Ops One", "display_name": "Black Ops One",
        "category": "机能展示", "weights": [400], "preview": "POWER 100%", "license": "OFL-1.1",
        "license_url": "https://github.com/google/fonts/blob/main/ofl/blackopsone/OFL.txt",
        "source_url": "https://raw.githubusercontent.com/google/fonts/main/ofl/blackopsone/BlackOpsOne-Regular.ttf",
        "file_name": "BlackOpsOne-Regular.ttf", "commercial_use": True, "coverage": "拉丁字母与数字",
        "tags": ["机能", "参数", "数字"],
    },
    {
        "id": "lobster", "name": "Lobster", "display_name": "Lobster",
        "category": "英文手写", "weights": [400], "preview": "Fresh Choice", "license": "OFL-1.1",
        "license_url": "https://github.com/google/fonts/blob/main/ofl/lobster/OFL.txt",
        "source_url": "https://raw.githubusercontent.com/google/fonts/main/ofl/lobster/Lobster-Regular.ttf",
        "file_name": "Lobster-Regular.ttf", "commercial_use": True, "coverage": "拉丁字母与数字",
        "tags": ["英文", "手写", "生活方式"],
    },
)


_BUNDLED_FONT_IDS = {
    item["id"] for item in _FONT_DEFINITIONS
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
            "license_verified": item.get("license") == "OFL-1.1" and bool(item.get("license_url")),
            "redistribution": "允许随软件嵌入和再分发；须保留 OFL-1.1 许可文本，不得单独出售字体文件。",
            "installed": available,
            "preview_available": available,
            "content_url": f"/api/fonts/{item['id']}/content",
        }

    def _bundled_path(self, item: dict[str, Any]) -> Path | None:
        if self.bundled_root is None or item["id"] not in _BUNDLED_FONT_IDS:
            return None
        path = self.bundled_root / item["file_name"]
        return path if path.exists() and 16_000 <= path.stat().st_size <= 40_000_000 else None
