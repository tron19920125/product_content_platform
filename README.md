# Product Content Platform

AI 商品图文内容生产与智能质检平台的新项目目录。

## 项目原则

- 以新的商品内容生产领域模型和页面流程为基础，不兼容原 MVP 的 Web 接口和页面结构。
- 生图、OCR、审查和评分能力已重构为平台内部模块，不依赖旧 MVP 的代码、目录或运行状态。
- 图片生成、OCR、审查计划、多模态质检和候选排序通过适配层逐步接入。
- 首期本地运行，支持单商品多页和多 SKU 批量生产。
- 使用“版式库 → 页面模板版本 → 配方 → 项目生产”的可审计配置体系；标题、正文和商品区域可在版式中心可视化编辑。

## 已完成范围

开发规格中的 P0 闭环已可以本地运行：

- 商品项目创建、复制、档案编辑、参考素材分类上传；
- 多页内容规划，支持增删、排序、修改、确认和 H1—H5 标题标签；
- AI 异步规划会基于商品事实、参考图和模板约束预填每页标题、正文与视觉目标，支持重新规划、逐页/逐字段采用、人工修改、事实来源审计、确定性降级和版本留痕；
- Prompt 版本、配方草稿/发布、已发布配方选择和项目效果沉淀；
- 文生图、参考图生成/编辑适配层，每页 1—3 个候选；
- 一个版式库固定一个画布尺寸；内置 `2048×2048` 正方形、`3840×2160` 最大横版和 `2160×3840` 最大竖版三套库，并允许在模型范围内新建自定义尺寸库；
- 页面模板按版本管理标题框、正文框、安全区、商品允许区和商品核心区；已发布版本不可原地修改，调整时必须创建新版本；
- 配方绑定可用模板版本、场景 Prompt、默认质量、候选数与质检策略；项目实际生产仍可覆盖本次质量；
- OCR/文字、安全区、主体遮挡、商品事实、品牌规则、参考一致性和多页样式证据；后期文字层是文案真值，OCR 的换行或标点偏差不会覆盖确定性排版证据；
- 平台内置审查计划、文字检查、视觉证据、候选评分排序和修复 Prompt；
- 排版问题自动调整，参考一致性问题自动重生成一次并保留修复前记录；
- 候选审核、P0/P1 覆盖原因、单页重生成，以及可修改字体风格、标题/正文字号与颜色、对齐、位置、行距后仅重排文字层；
- 任意候选图可追加自然语言视觉要求，只以该候选无字底图和原商品参考图为输入执行单图编辑，重新排版并仅质检目标页，同时保留原候选和版本谱系；
- 多候选勾选、上下调整顺序、纵向/横向原分辨率拼接、间距/背景/对齐设置和 PNG 长图导出；
- CSV/XLSX 多 SKU 导入、整批选配方、独立任务、失败隔离、暂停/继续、失败重试和按 SKU 目录导出；
- 生产阶段、百分比、尝试次数和耗时实时持久化展示；OCR/LLM 技术降级与图片质量问题分开提示；
- SQLite 与本地受控文件目录持久化，服务重启后会标记中断任务并允许定向重试；
- 业务用户与管理员/专家的本地简化角色切换。

本地默认使用确定性图片生成器和文字层质检，便于离线演示和回归。设置 `PCP_GENERATION_MODE=azure` 后，同一生产接口会切换到平台内置的 Azure 图片生成/编辑适配器；设置 `PCP_QA_MODE=azure` 后，会进一步启用 Azure AI Vision OCR、LLM 审查计划和多模态审查。两个开关相互独立，便于分别验证生成与质检链路。Azure 部署建议使用 Managed Identity，具体配置见 `docs/Azure部署配置教程.md`。

## 当前操作路径

1. 创建单商品项目，进入项目工作台。
2. 查看商品事实，上传商品、细节、品牌或场景参考素材。
3. 新建项目时先选择版式库；库卡片和后续模板预览都按实际宽高比缩放显示，不按像素等比放大页面。
4. 在管理员“版式中心”中维护同尺寸的页面模板：拖拽或缩放标题框、正文框、商品允许区与商品核心区，并配置页面类型和场景提示；发布后修改会自动进入新版本。
5. 在“生成配置”中选择或创建配方，绑定已发布模板、场景 Prompt、默认质量和质检策略；内置“高端生活场景演示配方”可直接体验。
6. 点击 AI 内容规划；按页或按字段采用建议，再人工修改标题、正文、视觉目标和兼容模板。重新规划不会直接覆盖当前版本。
7. 保存草稿或确认规划；确认后项目进入“已策划”状态。
8. 选择已发布配方和本次生成质量开始生产，查看质检问题和位置标注，对每页选择最终候选。
9. 在任一候选图上点击“继续修改此图”，输入背景、场景、光影、材质或角度等自然语言要求；系统只编辑该候选的无字底图，重新排版并仅质检本页，原候选保留。纯文字修改仍使用“调整文字排版”，不会调用生图模型。
10. 有两张及以上候选图时，可在“长图拼接与导出”中勾选图片、调整顺序、方向、对齐、间距和背景色，生成原始分辨率 PNG 长图。
11. 全部页面确认后导出 ZIP；对有效项目点击“沉淀为配方”，由管理员测试并发布。
12. 批量任务可选择快速录入或 CSV/XLSX 导入，按整批配方生产并进入各 SKU 审核。

## 随仓库提供的最小演示

首次启动会从 `examples/showcases/` 幂等创建三个已完成、可直接打开和导出的版式示例项目，不依赖数据库文件，也不需要调用 Azure：

- `2048×2048` 正方形：暖调家居洗护主视觉，文案位于左上；
- `3840×2160` 最大横版：宽幅现代洗衣空间，左侧留白、商品位于右侧；
- `2160×3840` 最大竖版：高挑建筑空间，顶部留白、商品位于下半部。

三例均保留 `base.png`、`text_layer.png` 和 `final.png`，可以验证“模型生成商品与场景、系统后排营销文字”的交付结构。要验证真实生产，可创建同尺寸项目、上传一张或多张有权使用的商品/细节参考图并开始生产；平台会把参考素材交给图片模型生成商品的新角度、材质表现和环境融合，营销标题与正文不会写入生图 Prompt。

仓库还保留 `examples/azure-five-page-acceptance/` 中的 `Azure 2048 High Five Page Acceptance` 历史验收快照。全新部署会按原项目 ID 恢复五页规划、五个 98 分候选、通过的 QA 和批准记录，因此可以直接打开和正式导出；它使用旧 `layered_product` 流程，仅作为历史回归证据，不代表当前推荐的多参考图 `model_edit` 链路。

版式库、模板、配方和单次 Prompt 的职责及完整链路见 [`docs/layout-library-guide.md`](docs/layout-library-guide.md)。
AI 规划建议、字段级采用、候选图定向修改与审计链路见 [`docs/ai-planning-and-candidate-edit.md`](docs/ai-planning-and-candidate-edit.md)。

## 目录

```text
product_content_platform/
├── backend/              Python 后端、领域模块和本地 Worker
│   └── src/product_content_platform/
│       ├── integrations/ 外部模型接入
│       └── quality/      OCR、审查、评分与修复
├── frontend/             React/TypeScript 前端
├── configs/              固定模板、品牌和质检配置
├── docs/                 项目内架构及开发文档
├── scripts/              本地安装、启动和测试脚本
└── tests/                跨模块及端到端测试
```

## 本地运行

需要 Python 3.11+、Node.js 20+ 和 pnpm（可由 Corepack 提供）。

首次安装：

```bash
./scripts/bootstrap_local.sh
```

推荐使用一条命令同时启动前后端。脚本会安全读取仓库根目录的 `.env`、记录 PID、执行健康检查，并将日志写入 `data/logs/`。
调用命令前已经设置的环境变量优先于 `.env`，因此可以在不修改配置文件的情况下临时切换本地模式或隔离数据目录。

Windows PowerShell：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_local.ps1
```

macOS / Linux：

```bash
./scripts/start_local.sh
```

例如，macOS 上临时用完全离线模式启动：

```bash
PCP_GENERATION_MODE=local PCP_QA_MODE=local ./scripts/start_local.sh
```

Windows PowerShell 中对应写法：

```powershell
$env:PCP_GENERATION_MODE="local"; $env:PCP_QA_MODE="local"; powershell -ExecutionPolicy Bypass -File .\scripts\start_local.ps1
```

停止全部服务：

```powershell
# Windows
powershell -ExecutionPolicy Bypass -File .\scripts\stop_local.ps1
```

```bash
# macOS / Linux
./scripts/stop_local.sh
```

只检查 `.env`、Python、Node 和前端依赖而不启动服务：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_local.ps1 -Check
```

```bash
./scripts/start_local.sh --check
```

需要分别调试后端和前端时仍可使用：

```bash
./scripts/dev_backend.sh
./scripts/dev_frontend.sh
```

后端已通过后台任务执行生产。需要单独恢复服务重启前遗留的排队任务时，可启动本地 Worker：

```bash
./scripts/dev_worker.sh
```

访问：

- 前端：http://127.0.0.1:5173/
- 后端接口文档：http://127.0.0.1:8000/docs
- Azure 环境预检：http://127.0.0.1:8000/api/preflight

首页左下角会异步显示本地或 Azure 环境状态。Azure 预检只验证路由配置和身份令牌，不调用图片、OCR 或 LLM 模型。

运行测试和前端构建：

```bash
./scripts/test_local.sh
```

产品范围和验收基线见：

- `docs/AI商品图文平台_MVP开发规格.md`
- `docs/AI商品图文内容生产与智能质检平台总体方案.md`
- `docs/AI商品图文内容生产与智能质检平台IP方案.md`
- `docs/spec-completion.md`
- `docs/acceptance-report.md`
