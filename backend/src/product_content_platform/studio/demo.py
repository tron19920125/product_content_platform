from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .catalog import DraftContent, SINGLE_PURPOSES, Tool, default_draft
from .creations import Creations
from .quality import Review
from .workspace import StudioWorkspace


class DemoPack:
    """Recorded Codex outputs, never a fallback for a failed live generation."""

    def __init__(self, workspace: StudioWorkspace, creations: Creations):
        self.workspace, self.creations = workspace, creations
        self.root = Path(__file__).resolve().parents[4] / "frontend" / "public" / "studio-demo"

    def manifest(self) -> dict:
        path = self.root / "manifest.json"
        if not path.is_file():
            return {"items": [], "description": "尚未安装演示素材包"}
        return json.loads(path.read_text(encoding="utf-8"))

    def create_draft(self, tool: Tool) -> dict:
        manifest = self.manifest()
        source = self.file(manifest["reference"]["file"])
        asset = self.workspace.upload_image(source.name, "product", source.read_bytes())
        draft = self.workspace.create_draft(tool)
        draft["content"].update(product_asset_ids=[asset["id"]], product_name="深色滚筒洗衣机", requirements="暖木家居风格，保留商品原始外观，不添加未经确认的参数。")
        self._fill_a_plus_plan(draft["content"], manifest)
        return self.workspace.save_draft(draft["id"], DraftContent.model_validate(draft["content"]), expected_revision=draft["revision"])

    def validate(self, operation: dict) -> None:
        content = operation["snapshot"]["content"]
        ids = content["product_asset_ids"]
        manifest = self.manifest()
        if len(ids) != 1 or content["style_asset_ids"] or content["logo_asset_id"]:
            raise ValueError("示例回放仅使用预置商品；自定义图片请提交 Codex 任务")
        path, _ = self.workspace.asset_file(ids[0], preview=False)
        reference = self.file(manifest["reference"]["file"])
        if hashlib.sha256(path.read_bytes()).digest() != hashlib.sha256(reference.read_bytes()).digest():
            raise ValueError("当前商品不是演示商品，不能用旧示例替代生成")
        if operation["kind"] != "generate":
            raise ValueError("自定义 AI 修改应提交 Codex；不能用未修改的示例冒充结果")

        # A recorded result is valid only for the exact pre-filled request. Page IDs
        # are local identity and intentionally excluded from the comparison.
        tool = Tool(content["tool"])
        expected = default_draft(tool).model_dump(mode="json")
        expected.update(
            product_name="深色滚筒洗衣机",
            requirements="暖木家居风格，保留商品原始外观，不添加未经确认的参数。",
            product_asset_ids=content["product_asset_ids"],
        )
        self._fill_a_plus_plan(expected, manifest)

        def comparable(value: dict) -> dict:
            result = dict(value)
            result["pages"] = [{key: item[key] for key in ("purpose", "title", "body", "visual_goal", "output", "skipped")} for item in value["pages"]]
            return result

        if comparable(content) != comparable(expected):
            raise ValueError("示例输入已改动，请提交 Codex 生成；不能用预置成图代替新请求")

    @staticmethod
    def _fill_a_plus_plan(content: dict, manifest: dict) -> None:
        if content.get("tool") != Tool.A_PLUS.value:
            return
        items = {item["purpose"]: item for item in manifest["items"] if item["tool"] == Tool.A_PLUS.value}
        for page in content["pages"]:
            item = items.get(page["purpose"])
            if item:
                page.update(title=item["title"], body=item["subtitle"], visual_goal=item["prompt"])

    @staticmethod
    def _matching_items(manifest: dict, tool: Tool, purpose: str) -> list[dict]:
        items = manifest["items"]
        if tool == Tool.A_PLUS:
            return [item for item in items if item["tool"] == Tool.A_PLUS.value and item["purpose"] == purpose]
        if tool == Tool.ECOM_SUITE:
            preferred = {
                "marketing": Tool.MARKETING.value,
                "scene": Tool.SCENE.value,
                "selling_point": Tool.SELLING.value,
            }.get(purpose)
            return [item for item in items if item["purpose"] == purpose and (preferred is None or item["tool"] == preferred)]
        return [item for item in items if item["tool"] == tool.value and item["purpose"] == SINGLE_PURPOSES[tool]]

    def replay(self, operation_id: str) -> None:
        while (job := self.creations.claim(operation_id)) is not None:
            try:
                operation = job["operation"]
                if operation["mode"] != "demo":
                    raise ValueError("非示例任务不能进行回放")
                self.validate(operation)
                page = next(page for page in operation["snapshot"]["pages"] if page["id"] == job["page_id"])
                purpose = page["purpose"]
                tool = Tool(operation["snapshot"]["content"]["tool"])
                items = self._matching_items(self.manifest(), tool, purpose)
                if not items:
                    raise ValueError("当前用途没有预置示例，请提交 Codex 进行生成")
                item = items[(job["variant"] - 1) % len(items)]
                path = self.file(item["file"])
                asset = self.workspace.upload_image(path.name, "style", path.read_bytes())
                self.creations.complete(job["id"], asset_id=asset["id"], review=Review.model_validate(item["review"]),
                                        provenance={"provider": "codex-recorded-demo", "demo_id": item["id"],
                                                    "note": "回放预置 Codex 成图，不是本次实时生成；保留示例实际像素，不按请求尺寸拉伸。"})
            except (ValueError, KeyError, OSError) as error:
                self.creations.fail(job["id"], message=str(error), outcome_known=True)

    def file(self, filename: str) -> Path:
        target = (self.root / filename).resolve()
        if target.parent != self.root.resolve() or not target.is_file():
            raise ValueError("演示文件不存在或路径无效")
        return target
