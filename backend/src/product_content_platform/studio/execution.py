from __future__ import annotations

import json

from .catalog import IMAGE_SIZES, TOOL_LABELS, DraftContent, purposes_for
from .workspace import StudioWorkspace


def package_job(job: dict, workspace: StudioWorkspace) -> dict:
    """Turn durable state into one self-contained, provider-neutral image task."""
    operation = job["operation"]
    snapshot = operation["snapshot"]
    content = DraftContent.model_validate(snapshot["content"])
    page = next(value for value in snapshot["pages"] if value["id"] == job["page_id"])
    output = page.get("output") or content.output.model_dump()
    width, height = IMAGE_SIZES[output["ratio"]][output["resolution"]]
    references = []
    for role, identifiers in (
        ("product", content.product_asset_ids), ("style", content.style_asset_ids),
        ("logo", [content.logo_asset_id] if content.logo_asset_id else []),
    ):
        for identifier in identifiers:
            path, media_type = workspace.asset_file(identifier, preview=False)
            references.append({"asset_id": identifier, "role": role, "path": str(path), "media_type": media_type})
    if job.get("source_version"):
        source = job["source_version"]
        path, media_type = workspace.asset_file(source["base_asset_id"], preview=False)
        references.append({"asset_id": source["base_asset_id"], "role": "edit_target", "path": str(path), "media_type": media_type})
    return {
        "job_id": job["id"], "operation_id": operation["id"], "kind": job["kind"],
        "tool": content.tool.value, "page_id": page["id"], "purpose": page["purpose"],
        "requested_output": {**output, "width": width, "height": height, "quality": "high"},
        "references": references, "prompt": _prompt(content, page, job),
        "completion": {
            "note": "生成后先按原商品参考检查 AI 底图；将图片和结构化检查结果交给 complete_codex_job.py。实际像素必须记录，不得用拉伸冒充请求尺寸。",
        },
    }


def package_review(task: dict, workspace: StudioWorkspace) -> dict:
    """Build an evidence-first QA task without including manual composition layers."""
    version = task["version"]
    content = None
    if version.get("operation_id"):
        with workspace._connect() as db:
            row = db.execute("SELECT snapshot FROM studio_operations WHERE id=?", (version["operation_id"],)).fetchone()
        if row:
            content = DraftContent.model_validate(json.loads(row["snapshot"])["content"])
    if content is None:
        # Versions restored from an independent work snapshot have no operation;
        # their copied draft is the immutable evidence boundary available to recheck.
        content = DraftContent.model_validate(workspace.get_draft(version["draft_id"])["content"])
    generated_path, generated_type = workspace.asset_file(version["base_asset_id"], preview=False)
    references = [{"role": "generated", "path": str(generated_path), "media_type": generated_type}]
    for identifier in content.product_asset_ids:
        path, media_type = workspace.asset_file(identifier, preview=False)
        references.append({"role": "product_reference", "path": str(path), "media_type": media_type})
    facts = [{"name": fact.name, "value": fact.value, "source": fact.source} for fact in content.facts]
    return {
        "review_task_id": task["id"], "version_id": version["id"], "attempt": task["attempt"],
        "references": references,
        "facts": facts,
        "instruction": (
            "只检查 AI 底图，不检查人工图层。对照商品参考检查外观结构、颜色、部件与 Logo；"
            "对照已提供事实检查文案；检查主体遮挡、裁切、对比度、边距和可读性。"
            "只有带明确视觉证据的错误可标为 error；无法确认的标为 uncertain，主观建议标为 suggestion。"
            "输出 Review JSON，未完成时 status=unavailable 且不填虚假分数。"
        ),
    }


def _prompt(content: DraftContent, page: dict, job: dict) -> str:
    label = purposes_for(content.tool)[page["purpose"]]
    language = "自然、准确的英文" if content.market == "amazon_en" else "简洁、准确的中文"
    facts = "；".join(f"{fact.name}={fact.value}（来源：{fact.source}）" for fact in content.facts) or "未提供可引用的规格事实"
    text = (
        "不添加营销文字，只保留商品本身已有的真实标识"
        if content.text_mode == "background_only" else
        f"图片文字使用{language}；标题：{page['title'] or '根据要求组织一般性表达'}；正文：{page['body'] or '可不添加正文'}"
    )
    instructions = [
        f"Use case: ads-marketing. Asset type: {TOOL_LABELS[content.tool]} / {label}.",
        "商品参考图用于锁定商品身份；必须保留可确认的外观、结构、颜色、门体方向、面板、Logo 和部件，不得重设计商品。",
        f"商品：{content.product_name or '未命名商品'}。制作要求：{content.requirements or '根据商品外观完成克制的电商表达'}。",
        f"画面目标：{page['visual_goal'] or content.style}。{text}。",
        f"品牌偏好：颜色 {content.brand_color or '未指定'}；字体风格 {content.brand_font}。未提供 Logo 时不得生成新 Logo。",
        f"可使用的事实只有：{facts}。不得编造型号、容量、尺寸、认证、功效、比较结论、价格或品牌历史。",
        "主体不得被文字或装饰遮挡；保证边距、对比度与可读性。单张完整图片，不要拼贴预览，不加水印。",
    ]
    if job["kind"] == "ai_edit":
        instructions.append(f"这是 AI 修改：只实施“{job['operation']['snapshot']['instruction']}”，其余画面和商品身份保持不变。")
    if job["kind"] == "repair" and job.get("source_version"):
        findings = job["source_version"]["review"].get("findings", [])
        issues = "；".join(value["message"] for value in findings if value["kind"] == "error") or "修正低分版本的可确认问题"
        instructions.append(f"这是一次且仅一次的自动修复：{issues}。不要借修复增加新卖点或改变无关内容。")
    return "\n".join(instructions)
