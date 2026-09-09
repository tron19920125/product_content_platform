# Product Content Studio

面向电商运营的本地 AI 商品内容创作工作台。用户不需要先建项目或配置模板，选择工具、上传商品图并设置输出参数即可开始。

## 产品范围

首期提供五个共用同一套数据、任务和编辑能力的入口：

- 电商套图：营销、场景、卖点等多页直接生成。
- A+ 详情图：先生成可编辑的模块方案，确认后再生图。
- 营销主图、场景图、卖点图：单图快速创作。

共用能力包括多视角商品参考、风格参考、品牌色/字体/Logo、中英文预设、生成前尺寸与候选数设置、AI 修改、独立图层手动编辑、质检与一次低分修复、版本溯源、素材/作品快照、创作历史、回收站及 PNG/JPG/ZIP/长图导出。

## 当前执行方式

新 Studio 默认不读取旧 `.env`，不调用 Azure，也不依赖旧平台的项目、模板、审批或演示数据。

- 六张 Codex 生成的商品图已作为静态示例资源随前端提供，可直接浏览；“回放示例”会明确标记来源，不冒充本次实时生成。
- 默认手动模式下，自定义生图生成持久化队列，由 `scripts/next_codex_job.py` 和 `scripts/complete_codex_job.py` 辅助执行。
- 显式启用 Azure 后，服务自带常驻执行器，自动处理普通生图、AI 修改和一次低分修复；示例回放保持独立。图片收到后先保存，再由独立队列完成质检。
- A+ 规划在 Azure 模式下使用原文案模型，手动模式下使用本机 Codex CLI 适配器；商品图不随规划请求发送。
- 质检对 AI 底图生效，人工图层不重检。质检服务失败最多自动重试两次，仍失败时保留“检查未完成”，可手动重检。

Codex 辅助执行的具体操作见 [`docs/本地Codex执行说明.md`](docs/本地Codex执行说明.md)。

### 服务配置提醒

右上角“服务配置”显示创作服务、自动生图、智能规划、Azure 接入和示例回放的实际状态。页面会定期检查连接，也可手动“重新检测”；断线时保留当前输入并提示恢复服务。

手动模式下，自定义任务先提示“仅加入队列”。Azure 模式下，认证检查通过后自动执行；配置错误时阻止新提交并显示恢复步骤。排队任务显示“等待执行”，只有领取后的任务才显示“生成中”。页面提供认证、权限、端点、配额与网络错误提示，不返回服务端密钥或原始错误响应。

已有排队任务会继续处理，无需重复提交。明确失败的任务可手动重试；超时或连接中断导致的结果待确认任务不会自动重发。服务中断时，已保存的 Azure 响应会在下次启动时恢复成图；没有收到响应的任务保留“结果待确认”。同一工作区只允许一个服务进程，避免重复执行和错误恢复。

### 恢复原 Azure 配置（Windows）

在构建前端后运行 `scripts/start_studio.ps1`，会显式读取仓库 `.env` 中的 `AZURE_*` 配置，启用后台执行器并保留独立的 `data-refactor/` 数据目录。不会加载旧版 `PCP_DATA_ROOT` 等设置，也不会改写 `.env`。日志位于 `.run/studio-azure-*.log` 和 `data-refactor/logs/backend.log`。

```powershell
.\scripts\start_studio.ps1
```

也可前台启动（先设置 `PYTHONPATH=backend/src`）：

```powershell
.\.venv\Scripts\python.exe -m product_content_platform.studio --port 8010 --azure-env .env
```

通过已有进程环境配置时，设置 `PCP_STUDIO_GENERATION_PROVIDER=azure`；省略则保持手动模式。认证支持原 `AZURE_AUTH_MODE`、图像端点/部署、文案模型及 API Key/Entra 登录。恢复登录后可在网页重新检测；修改配置文件后需要重启服务。停止服务前应等待执行中的请求完成。

## 本地启动

需要 Python 3.11+ 及已安装的前端依赖。首次准备可使用现有安装脚本：

```bash
./scripts/bootstrap_local.sh
```

构建前端后启动独立 Studio：

```bash
cd frontend && pnpm build && cd ..
bash scripts/start_studio.sh
```

访问 `http://127.0.0.1:8010/`。服务默认只绑定回环地址，数据保存在仓库下被 Git 忽略的 `data-refactor/`。可通过 `PCP_STUDIO_DATA_ROOT`、`PCP_STUDIO_PORT` 和 `PCP_STUDIO_MAX_REFERENCES` 调整新 Studio 的独立配置。

只检查环境而不创建数据或启动服务：

```bash
bash scripts/start_studio.sh --check
```

## 验证

```bash
./.venv/bin/python -m unittest discover -s backend/tests -p 'test_*.py'
cd frontend && pnpm run build
```

重构的产品、交互及验收基线见 [`docs/商品内容平台_重构实施规格.md`](docs/商品内容平台_重构实施规格.md)，实际进度及未完成的外部验证见 [`docs/重构实施记录.md`](docs/重构实施记录.md)。

## 新版核心目录

```text
backend/src/product_content_platform/studio/   独立后端与状态模型
frontend/src/studio/                           新工作台、编辑器与导出
frontend/public/studio-demo/                   可直接浏览的 Codex 示例素材
scripts/start_studio.sh                        独立本地启动器
scripts/next_codex_job.py                      领取一个生图/修复任务
scripts/complete_codex_job.py                  保存成图与质检结果
scripts/next_codex_review.py                   领取一个质检或重检任务
scripts/complete_codex_review.py               保存质检或记录失败重试
```
