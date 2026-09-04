# Backend

当前重构版的独立后端位于 `src/product_content_platform/studio/`，由 `scripts/start_studio.sh` 启动。

它以 FastAPI、SQLite 和本地文件为基础，统一管理五个创作工具的草稿、按候选拆分的任务、版本、AI 底图质检、一次低分修复、素材/作品快照与 30 天回收站。新模块不调用旧平台的项目、模板、配方、审批或 Azure 适配器。

核心路由：

- `GET /api/health`
- `/api/studio/drafts` 与 `/api/studio/history`
- `/api/studio/assets` 与 `/api/studio/library`
- `/api/studio/drafts/{id}/generate` 与 `/api/studio/execution/*`
- `/api/studio/versions/*` 与 `/api/studio/reviews/*`

生图和质检执行器通过持久化队列边界接入，不能改写已提交的输入快照或重置修复次数。
