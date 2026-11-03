from __future__ import annotations

import json

from .catalog import IMAGE_SIZES, TOOL_LABELS, DraftContent, purposes_for
from .briefs import purpose_direction
from .workspace import StudioWorkspace
from .creations import Creations


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
        target_id = source["render_asset_id"] if job["kind"] == "repair" and source.get("kind") == "manual" else source["base_asset_id"]
        path, media_type = workspace.asset_file(target_id, preview=False)
        references.append({"asset_id": target_id, "role": "edit_target", "path": str(path), "media_type": media_type})
    # This is also the image order sent by AzureServices.generate.
    references.sort(key=lambda value: value["role"] != "edit_target")
    roles = {"product": "商品身份依据", "style": "只参考颜色、构图与氛围，不采用其中的商品、文字或事实", "logo": "用户提供的 Logo", "edit_target": "待修改的当前图片，修改范围以本次要求为准"}
    reference_map = "\n".join(f"输入图片 {index + 1}：{roles[value['role']]}。" for index, value in enumerate(references))
    copy_request = _review_brief(content, page)
    copy_request.update(enabled=copy_request["check_copywriting"], facts=[fact.model_dump(mode="json") for fact in content.facts])
    if job["kind"] == "ai_edit":
        copy_request.update(enabled=True, allow_empty=True, title="", body="")
    source_copy = job.get("source_version", {}).get("provenance", {}).get("copy_plan")
    if job["kind"] == "repair" and source_copy is not None:
        # A repair must retain the approved text of the version being repaired,
        # including text added or removed by a later AI edit.
        copy_request.update(enabled=bool(source_copy["lines"]), allow_empty=True, title="", body="")
    if job["kind"] == "repair" and job.get("source_version", {}).get("kind") == "manual":
        copy_request.update(enabled=False, title="", body="")
    return {
        "job_id": job["id"], "operation_id": operation["id"], "kind": job["kind"],
        "tool": content.tool.value, "page_id": page["id"], "purpose": page["purpose"],
        "requested_output": {**output, "width": width, "height": height, "quality": "high"},
        "references": references, "prompt": _prompt(content, page, job) + "\n" + reference_map,
        # Editing existing copy requires its own scope; keep that scope visible to the preparer.
        "copy_request": {**copy_request, "kind": job["kind"], "edit_instruction": snapshot.get("instruction", ""),
                         "source_copy": source_copy},
        "completion": {
            "note": "生成后先按原商品参考检查 AI 底图；将图片和结构化检查结果交给 complete_codex_job.py。实际像素必须记录，不得用拉伸冒充请求尺寸。",
        },
    }


def package_review(task: dict, workspace: StudioWorkspace) -> dict:
    """Review the current rendered image against its original creation brief."""
    version = task["version"]
    with workspace._connect() as db:
        snapshot = Creations.version_snapshot(db, version)
    content = DraftContent.model_validate(snapshot["content"])
    generated_path, generated_type = workspace.asset_file(version["render_asset_id"], preview=False)
    references = [{"role": "generated", "path": str(generated_path), "media_type": generated_type}]
    for identifier in content.product_asset_ids:
        path, media_type = workspace.asset_file(identifier, preview=False)
        references.append({"role": "product_reference", "path": str(path), "media_type": media_type})
    if version.get("parent_id"):
        with workspace._connect() as db:
            parent = Creations._version(db, version["parent_id"])
        path, media_type = workspace.asset_file(parent["render_asset_id"], preview=False)
        references.append({"role": "before_edit", "path": str(path), "media_type": media_type})
    facts = [{"name": fact.name, "value": fact.value, "source": fact.source} for fact in content.facts]
    pages = snapshot["pages"] if snapshot else [page.model_dump(mode="json") for page in content.pages]
    page = next((page for page in pages if page["id"] == version["page_id"]), None)
    brief = _review_brief(content, page)
    brief["manual_composition"] = version["kind"] == "manual"
    if version["kind"] == "manual":
        brief["manual_text"] = [layer.get("text", "") for layer in version.get("layers", [])
                                if layer.get("type") == "text" and not layer.get("hidden") and layer.get("text", "").strip()]
    brief["edit_instruction"] = snapshot.get("instruction", "") if snapshot else ""
    if version.get("provenance", {}).get("copy_plan") is not None:
        brief["approved_copy"] = version["provenance"]["copy_plan"]
        brief["check_copywriting"] = bool(brief["approved_copy"]["lines"])
    return {
        "review_task_id": task["id"], "version_id": version["id"], "attempt": task["attempt"],
        "references": references,
        "facts": facts,
        "brief": brief,
        "instruction": (
            "输入 generated 是当前版本完整成图，其中所有可见文字、标题、图标都需要检查。"
            "manual_composition=true 时包含人工编辑，不沿用 AI 底图的旧点评，应以当前可见内容为准；"
            "manual_text 是用户已应用的排字内容，不要求恢复旧文案，仍核对当前文案的事实与可读性。"
            "before_edit 只用于对比修改范围和无关区域是否保留，不能当作待点评图片。"
            "对照商品参考检查外观结构、颜色、部件与 Logo；对照本页创作任务检查用途、构图、标题和正文是否落实。"
            "本页文字规则优先于未启用的标题正文；只生成底图时不能把缺少营销文字当作错误。若有 edit_instruction，应按本次修改要求验收，不能把用户明确要求改掉的旧文案当作缺失。"
            "如果提供了 approved_copy，核对原图营销文字是否逐字符合该清单；不能增写、改写或漏写。清单优先于默认文案建议，多出的无依据功能或性能承诺属于关键错误。"
            "即使 facts 为空，也要检查图中文字的可读性、错字、任务完成度及是否出现无依据的参数或功效；"
            "外观特点可以由清晰商品参考支持，不能由外观推断性能。需要文案时，在点评中明确说明文案与用途的完成情况。"
            "卖点图必须具体解释特点并对应细节；只有口号没有特点、明确要求的核心文案缺失、凭空声称功效或规格，"
            "均应在有视觉证据时给出具体问题和依据，并提供不编造事实的修改建议。"
            "检查主体遮挡、裁切、对比度、边距和可读性。"
            "只有带明确视觉证据的错误可标为 error；无法确认的标为 uncertain，主观建议标为 suggestion。"
            "Logo 或面板细字疑似缺字时，必须能从参考和成图分别明确辨认正确与错误字符，才可断言错字；"
            "反光、模糊或低分辨率导致无法逐字确认时，应报告 uncertain，不能把猜测当成关键错误。"
            "营销图关注主体和标题层级；场景图关注使用环境、比例和光影；卖点图关注特点与细节的对应。"
            "认可有依据的优点，主观审美建议明确标为 suggestion，不判定必须修改。输出 Review JSON，不输出分数或等级。"
        ),
    }


def _review_brief(content: DraftContent, page: dict | None) -> dict:
    return {
        "tool": content.tool.value, "purpose": page["purpose"] if page else None,
        "purpose_direction": purpose_direction(page["purpose"]) if page else "",
        "title": page["title"] if page else "", "body": page["body"] if page else "",
        "visual_goal": page["visual_goal"] if page else "", "requirements": content.requirements,
        "text_mode": content.text_mode, "market": content.market,
        "text_rule": _text_instruction(content, page) if page else "按所选文字模式检查",
        "check_copywriting": content.text_mode == "native" and (not page or (
            page["purpose"] != "white_background" and (page["purpose"] != "scene" or bool(page["title"].strip() or page["body"].strip())))),
        "brand_color": content.brand_color, "brand_font": content.brand_font,
    }


def _text_instruction(content: DraftContent, page: dict) -> str:
    language = "自然、准确的英文" if content.market == "amazon_en" else "简洁、准确的中文"
    if content.text_mode == "background_only" or page["purpose"] == "white_background":
        text = "不添加标题、营销文字或特点标签，只保留商品本身已有的真实标识；卖点用对应细节和构图表达，留出后续排字空间。此文字模式优先于其他文案要求"
    elif page["purpose"] == "scene" and not (page["title"].strip() or page["body"].strip()):
        text = "本页未指定标题正文，以真实环境叙事为主，不自动套用营销主图的大标题与口号"
    else:
        text = f"图片文字使用{language}；用户指定标题：{page['title'] or '未指定，按本页用途写具体、简短的标题'}；用户指定正文：{page['body'] or '未指定；卖点页需按特点写短标签，其他用途保持简洁'}。明确给出的标题与正文应准确呈现；未经事实支持的参数或功效不能因为写进要求就变成事实"
    return text


def _prompt(content: DraftContent, page: dict, job: dict) -> str:
    label = purposes_for(content.tool)[page["purpose"]]
    facts = "；".join(f"{fact.name}={fact.value}（来源：{fact.source}）" for fact in content.facts) or "未提供可引用的规格事实"
    text = _text_instruction(content, page)
    instructions = [
        f"Use case: ads-marketing. Asset type: {TOOL_LABELS[content.tool]} / {label}.",
        "商品参考图用于锁定商品身份；必须保留可确认的外观、结构、颜色、门体方向、面板、Logo 和部件，不得重设计商品。",
        "锁定商品参考图已有的拍摄视角和可见侧面；通过平移主体、背景与留白做构图，不水平镜像商品、不换到参考图没有提供的另一侧。"
        "显示屏、旋钮、标识和小字属于商品身份的一部分，应忠实沿用参考，不重新编写面板文案、数字或规格。不清楚的细小字符不得靠常识补齐，更不能变成新的醒目参数。",
        f"商品：{content.product_name or '未命名商品'}。制作要求：{content.requirements or '根据商品外观完成克制的电商表达'}。",
        f"本页用途与构图任务：{purpose_direction(page['purpose'])}",
        f"用户补充画面目标：{page['visual_goal'] or '未指定，执行上述用途构图'}。全组风格：{content.style}。{text}。",
        f"品牌偏好：颜色 {content.brand_color or '未指定'}；字体风格 {content.brand_font}。未提供 Logo 时不得生成新 Logo。",
        f"可使用的规格事实只有：{facts}。不得编造型号、容量、尺寸、认证、功效、比较结论、价格或品牌历史。",
        "没有规格事实时，仅以商品参考中清楚可见的形状、颜色、表面与部件作为特点依据；不要将其扩展为材质、性能、舒适度或功效承诺。不能从同类商品常识或风格图补卖点。",
        "主体不得被文字或装饰遮挡；保证边距、对比度与可读性。只输出本页一张成品设计，不要输出整组缩略图或多张海报拼贴；卖点、细节等用途允许在同一张设计内安排有层级的局部特写。不加水印。",
    ]
    if job["kind"] == "generate":
        siblings = [value for value in job["operation"]["snapshot"]["pages"] if not value.get("skipped")]
        if len(siblings) > 1:
            roles = "；".join(f"{purposes_for(content.tool)[value['purpose']]}：{purpose_direction(value['purpose'])}" for value in siblings)
            instructions.append("整组分工（只生成当前页）：" + roles + "统一色调、字体气质和商品身份，但各用途的镜头远近、商品占比、信息密度和构图必须明显不同，不要只换标题和背景。")
        if job.get("variant", 1) > 1:
            instructions.append(f"本页候选 {job['variant']}：在用途与事实不变的前提下探索不同主体位置、留白和视觉节奏，不改变商品结构。")
    if job["kind"] == "ai_edit":
        instructions.append(f"这是 AI 修改：只实施“{job['operation']['snapshot']['instruction']}”，其余画面和商品身份保持不变。上述用途方向仅作背景，不要求借此重新设计整页；以修改范围为准。")
    if job["kind"] == "repair" and job.get("source_version"):
        issues = job["operation"]["snapshot"].get("instruction", "")
        instructions.append(f"这是用户在点评完成后主动请求的修复，仅实施以下修改：{issues}。保留当前画面优点及所有无关区域；不得自行处理待核对的疑点、编造参数或增加卖点。上述用途方向仅作背景，不借此重新设计整页。")
        if job["source_version"].get("kind") == "manual":
            instructions.append("输入待修改图包含用户已经应用的人工排字。保留这些文字及其排版，除非上述修改明确要求调整；不根据早期文案要求覆盖现有内容。")
    return "\n".join(instructions)
