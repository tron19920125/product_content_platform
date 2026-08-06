# Backend

后端采用 Python 和 FastAPI，已建立以下模块：

- `domain`：项目、商品档案、页面计划、配方、批次、候选和质检结果；
- `application`：内容策划、生成、质检、审核、导出和批量调度；
- `adapters`：原 MVP、模型、OCR、数据库和本地文件存储适配器；
- `api`：本地 Web 接口；
- `worker`：生成、OCR、质检、合成和导出任务执行。

主要资源边界：

- `GET /api/health`
- `/api/projects`：项目、档案、复制、素材和页面规划；
- `/api/projects/{id}/production`：整套生产、单页重生成、仅重排、审核和导出；
- `/api/prompts` 与 `/api/recipes`：版本、草稿和发布；
- `/api/batches`：多SKU导入、生产、暂停/继续、失败重试和批量导出；
- `/api/jobs`：任务查询和排队任务恢复；
- `/api/candidates`：候选文件与人工决策。

项目和批次通过应用模块访问，不直接依赖 FastAPI 或 SQLite。生产流程通过深模块接口隔离图片模型、质检实现、文件存储和压缩导出。
