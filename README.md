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
- 自定义生图会按页和候选数生成持久化任务，由 Codex 执行端领取。仓库提供 `scripts/next_codex_job.py` 和 `scripts/complete_codex_job.py`，目前不宣称已有常驻的全自动图片 Worker。
- A+ 规划已接入本机 Codex CLI 适配器，在当前运行环境允许外部文本处理时执行。界面在每次发送前明确告知范围；商品图不随规划请求发送。
- 质检对 AI 底图生效，人工图层不重检。质检服务失败最多自动重试两次，仍失败时保留“检查未完成”，可手动重检。

Codex 辅助执行的具体操作见 [`docs/本地Codex执行说明.md`](docs/本地Codex执行说明.md)。

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
