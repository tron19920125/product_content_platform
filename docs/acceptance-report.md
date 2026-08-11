# MVP 验收报告

验收日期：2026-08-11

## 结论

本文件主体记录 2026-08-11 完成的旧 `layered_product` 五页验收，作为历史回归基线保留。当前默认正式链路已迁移为“多参考图由模型直接生成商品与场景 + 确定性文字排版”；旧记录中的商品分层合成和 `product_layer.png` 不再代表推荐方案。

MVP 已完成从模板、配方、Prompt、参考素材、真实 Azure 场景生图、确定性文字排版、OCR/LLM 质检、人工审核到正式导出的闭环。Windows 可用一条 PowerShell 命令启动/停止前后端；macOS/Linux 提供等价的一条 Bash 命令。仓库不包含 `.env`、密钥、数据库、用户素材、日志或真实生成文件。

## 当前多参考模型生成验收（2026-08-11）

- 项目：`b9ca13d8-4f90-489a-bca1-205eba56984a`，候选：`be28494f-f7e3-42c7-8deb-76baeceaf0aa`。
- 输入：同一商品的 1 张商品外观图和 1 张局部细节图；任务追踪与生成元数据均记录 `reference_count=2`，无参考图被省略。
- 生成：Azure `2048x2048 / high / model_edit / input_fidelity=high`，图片输入 token 为 2048；`product_generated_by_model=true`。
- 分层：`base.png` 已包含模型生成的商品与场景，系统只追加 `text_layer.png`；不存在 `background.png` 或 `product_layer.png`，因此不是商品贴图流程。
- 质检：单候选完成，QA `pass / 98`，无 P0—P3 问题；页面显示 2 张参考图、100% 完成和 3 分 34 秒实际用时。
- 视觉：商品与木饰面柜体、石材地面、窗光、接触投影和环境反射自然融合，左上留白由确定性文字层排版，满足当前最小演示验收。

## 可直接演示的案例

- 入口：`新建项目 → 创建黄金演示项目`。
- 配方：`高端生活场景演示配方`（`commerce-lifestyle-demo-v1`）。
- 默认模板：`2048x2048`；默认质量：`High`；候选数：1。
- 策略：图片模型只生成无商品、无营销文字的完整生活场景；系统从用户参考图合成商品层，再生成确定性文字层。
- 必需输入：一张用户有权使用、背景干净且商品完整的正面或 45° 商品参考图。

## 真实 Azure 五页全量验收

- 项目：`Azure 2048 High Five Page Acceptance`
- 项目 ID：`2b5deb3c-e86b-4cfa-85b5-7429536e91f0`
- SKU：`DEMO-LIFE-2048`
- 模型提供方：`azure-gpt-image`
- 实际参数：5 页全部 `2048x2048 / high / layered_product`
- 页面：主视觉、卖点、功能、生活场景、参数，共 5 页。
- 图片模型调用：每页 1 次，单页模型耗时约 123～133 秒；无 400、404、SSL 或鉴权失败。
- QA：5 个最新候选全部 98 分、`pass`、0 条问题；5 页全部批准，项目状态 `completed`。
- 修复闭环：第 1 页首次因亮背景上的白色 `10kg` 可读性不足得到 P1。系统改为按实际文字覆盖区域选择颜色，只重新排版和审查、不重新生图，最终 98 分通过。
- 正式导出：`data/exports/DEMO-LIFE-2048_Azure_2048_High_Five_Page_Acceptance_106bb05e.zip`（运行时文件，已被 Git 忽略）。
- 导出验证：78.6 MB、31 个条目；每页包含 `final.png`、`base.png`、`background.png`、`product_layer.png`、`text_layer.png`、`qa.json`，另含 `project_summary.json`。
- 溯源验证：清单的每一页都记录 `recipe_id`、`prompt_version_id`、模型、生成提供方、实际尺寸/质量、模板、参考策略和图层列表。

## 配方沉淀与复用

- 单页黄金案例项目：`463af994-5749-4db1-bc6e-09852b77d7e6`。
- 实际 Azure 单图：`2048x2048 / High`，底图生成约 133 秒，最终 98 分通过并批准。
- 项目已沉淀为配方并发布：`7b48c647-7ea8-4639-bdcf-a13b7bdf9183`。
- 已验证发布配方可被另一个项目选择并完整生产；正式导出保留配方与生成参数溯源。

## 本地五 SKU 与恢复验收

- 隔离数据目录：`data/acceptance_local_20260811`（运行时目录，已被 Git 忽略）。
- 批次：`local-5-sku-acceptance`，批次 ID `33d54c9b-5255-4d36-b983-3897f2d44e80`。
- 规模：5 个 SKU、每个 5 页，共 25 个候选。
- 结果：25/25 候选审核完成，5/5 SKU 完成，0 失败。
- 批量导出：2.27 MB、106 个条目，包含 5 个独立 SKU 根目录。
- 恢复：停止并用一键脚本重启服务后，健康检查通过，批次仍为 `completed 5/5`；自动化测试另覆盖运行中任务被中断后的可解释失败与定向重试。

## 启动与环境

Windows：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_local.ps1
```

macOS / Linux：

```bash
./scripts/start_local.sh
```

两套脚本均安全解析 `.env`，不会执行其中的命令；调用方已设置的变量优先，可临时切换本地/Azure 模式或隔离数据目录。Windows 已实机验证启停和健康检查。当前验收主机为 Windows，无法声称在物理 Mac 上实跑；Bash 脚本使用 macOS 原生可用的 `bash`、`curl`、`nohup`、`kill`、`node` 和 `.venv/bin/python` 路径，不依赖 GNU 专属启动参数。

## 自动化与构建

- 后端：67 项 `unittest` 全部通过。
- 前端：TypeScript 项目构建与 Vite 生产构建通过。
- Azure 预检：图片生成、Vision OCR、LLM 审查三个组件均为 `ready`，并成功取得 Azure 身份令牌。

## Git 回滚点

- `49eb9a1`：可配置图片生产基线。
- `4cee13a`：跨平台启动与 Azure 预检。
- `57163b2`：参考商品分层合成。
- `40cbc94`：生产阶段与可信 QA 证据。
- `13908f4`：可复现洗护黄金案例。
- `2c59503`：配方复用与交付溯源。
- `79ddf72`：本地五 SKU 与服务重启验收。
- `7c650ff`：真实 Azure 五页全量验收、排版对比度修复、导出溯源与完整文档。
