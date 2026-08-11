# Azure 部署配置教程

本文档说明商品图文平台连接 Azure OpenAI 和 Azure AI Vision 时需要完成的资源、身份、权限及环境变量配置。生产环境统一建议使用 Managed Identity，不保存长期密钥或短期 Bearer Token。

## 1. 准备 Azure 资源

需要准备以下资源：

| 资源 | 用途 | 要求 |
| --- | --- | --- |
| Azure OpenAI / Foundry 模型资源 | 商品图生成、图片编辑、审查计划、多模态质检 | 创建图片模型部署和多模态审查模型部署 |
| Azure AI Vision | OCR 文字识别 | 使用资源页面提供的自定义 Endpoint |
| Azure 应用承载服务 | 运行后端 | 可使用 App Service、Container Apps 或虚拟机 |

内置模板默认配置为 `quality=high`、`size=2048x2048`。质量是配方默认值，实际生产可在 `low`、`medium`、`high` 中临时覆盖；尺寸由页面模板决定，不再由生产环境变量全局覆盖。常用预设包含 `1024x1024`、`1536x1024`、`1024x1536`、`2048x2048`、`2048x1152`、`1152x2048`、`2560x1440` 和 `1440x2560`。自定义模板会校验 `gpt-image-2` 的边长、宽高比、16 像素倍数和总像素限制；最大正方形为 `2880x2880`，总像素上限为 8,294,400。4K 横竖版和最大正方形在界面中会标记为实验性。

## 2. 启用 Managed Identity

进入承载后端的 Azure 服务，在“标识（Identity）”页面选择一种方式：

- 系统分配托管身份：打开“系统分配”并保存，适合单个部署独立使用；
- 用户分配托管身份：创建或选择已有身份并关联到承载服务，适合多个部署共享身份。

使用用户分配身份时，记录身份的 **Client ID**。后续配置不能使用 Object ID、Principal ID 或 Azure 资源 ID 代替。

## 3. 分配资源权限

在目标资源的“访问控制（IAM）”中，选择“添加角色分配”，将角色授予上一步启用的托管身份：

| 目标资源 | 角色 | 平台用途 |
| --- | --- | --- |
| Azure OpenAI / Foundry 模型资源 | `Cognitive Services OpenAI User` | 生图、图片编辑和多模态审查 |
| Azure AI Vision 资源 | `Cognitive Services User` | OCR 识别 |

角色范围建议限定在对应资源。角色分配通常需要数分钟传播，配置后立即出现 403 时可稍后重试。

## 4. 配置生产环境变量

在 App Service 的“配置”、Container Apps 的“环境变量”或实际容器编排配置中添加：

```dotenv
PCP_GENERATION_MODE=azure
PCP_QA_MODE=azure
PCP_IMAGE_QUALITY=high
PCP_MAX_IMAGE_REFERENCES=6

AZURE_AUTH_MODE=managed_identity

AZURE_OPENAI_RESOURCE_ENDPOINT=https://<openai-resource>.openai.azure.com
AZURE_OPENAI_IMAGE_DEPLOYMENT=<gpt-image-2-deployment-name>
AZURE_OPENAI_IMAGE_API_VERSION=2025-04-01-preview
AZURE_OPENAI_IMAGE_EDIT_API_VERSION=2025-04-01-preview

AZURE_OPENAI_REVIEW_MODEL=<multimodal-review-deployment-name>
AZURE_OPENAI_REVIEW_API_VERSION=2025-04-01-preview

AZURE_AI_VISION_ENDPOINT=https://<vision-resource>.cognitiveservices.azure.com
```

系统分配身份不配置 Client ID。用户分配身份需额外配置：

```dotenv
AZURE_MANAGED_IDENTITY_CLIENT_ID=<managed-identity-client-id>
```

Managed Identity 模式下，下列静态凭据应删除或留空：

```dotenv
AZURE_OPENAI_BEARER_TOKEN=
AZURE_OPENAI_API_KEY=
AZURE_AI_VISION_BEARER_TOKEN=
AZURE_AI_VISION_KEY=
```

平台通过 `azure-identity` 为每次调用取得有效令牌，SDK 会处理令牌缓存和续期，不需要人工定时更新 Bearer Token。

## 5. Endpoint 的两种配置方式

推荐配置资源 Endpoint、部署名和 API Version，由平台按 Azure OpenAI v1 格式拼接请求地址，并将部署名写入请求体的 `model` 字段。也可以直接提供完整地址，完整地址的优先级更高：

```dotenv
AZURE_OPENAI_IMAGE_ENDPOINT=https://<resource>.services.ai.azure.com/openai/deployments/<deployment>/images/generations?api-version=2025-04-01-preview
AZURE_OPENAI_IMAGE_EDIT_ENDPOINT=https://<resource>.services.ai.azure.com/openai/deployments/<deployment>/images/edits?api-version=2025-04-01-preview
AZURE_OPENAI_REVIEW_ENDPOINT=https://<resource>/openai/responses?api-version=<version>
```

如果使用 Foundry Project 的 OpenAI-compatible v1 图片路由，应直接配置完整地址：

```dotenv
AZURE_OPENAI_IMAGE_ENDPOINT=https://<account>.services.ai.azure.com/api/projects/<project-name>/openai/v1/images/generations
AZURE_OPENAI_IMAGE_EDIT_ENDPOINT=https://<account>.services.ai.azure.com/api/projects/<project-name>/openai/v1/images/edits
```

`/openai/v1/` 路由不得附加 `api-version` 查询参数；平台也会主动移除项目级 v1 图片地址上的该参数。部署式 `/openai/deployments/...` 路由则必须使用资源支持的 API Version。两种形式不要混用，否则常见结果是 400 `api-version query parameter is not allowed` 或 400 `API version not supported`。

## 6. 本地联调配置

本地机器不存在 Managed Identity。先使用 Azure CLI 登录，并确保当前账号拥有第 3 节中的资源角色：

```bash
az login
```

复制示例配置并将鉴权模式改为：

```dotenv
AZURE_AUTH_MODE=default_credential
```

一键启动脚本会将 `.env` 按纯 `KEY=VALUE` 数据安全加载，不执行其中的命令。Windows 使用：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_local.ps1
```

macOS / Linux 使用：

```bash
./scripts/start_local.sh
```

`DefaultAzureCredential` 在本地读取 Azure CLI 登录身份；生产环境仍建议明确使用 `managed_identity`。

启动后可访问 `http://127.0.0.1:8000/api/preflight`，或展开前端左下角的环境状态。该预检会验证 Endpoint 结构并尝试获取 Azure 身份令牌，但不会调用图片、OCR 或 LLM 模型。

## 7. 上线前验证

按以下顺序验证：

1. 确认后端安装了项目依赖，其中包含 `azure-identity`；
2. 确认后端服务已经关联正确的托管身份；
3. 确认该身份在 OpenAI 和 Vision 两个资源上均拥有对应角色；
4. 重启服务，使环境变量生效；
5. 选择 `2048x2048` 模板执行一次单图 `High` 生产，确认模型生成图、文字层与合成图均为模板尺寸；
6. 上传两张以上同一商品的外观/细节参考图，选择“多参考图生成商品”，确认调用图片编辑 Endpoint、候选元数据中的 `product_generated_by_model=true`、`reference_count` 正确且没有 `product_layer.png`；`PCP_MAX_IMAGE_REFERENCES` 默认 6，允许 1—16；
7. 开启 Azure 质检，确认 OCR、审查计划和多模态审查均能返回结果；
8. 若资源使用防火墙或私有终结点，确认承载服务的网络和 DNS 能访问资源 Endpoint。

常见错误：

| 状态 | 优先检查 |
| --- | --- |
| 401 | Managed Identity 是否启用、Client ID 是否填错、请求资源是否支持 Entra 鉴权 |
| 403 | IAM 角色是否正确、角色是否分配到正确资源、角色是否完成传播 |
| 404 | Endpoint、部署名或 API Version 是否匹配 |
| 400 size/quality 错误 | 图片模型是否为 `gpt-image-2`，以及当前 API Version 是否支持所配参数 |
| 连接超时 | 防火墙、私有终结点、VNet、DNS 和出站访问规则 |

## 8. 官方参考

- [Azure OpenAI 图片生成模型与参数](https://learn.microsoft.com/en-ca/azure/ai-foundry/openai/how-to/dall-e?view=foundry)
- [Azure OpenAI Managed Identity 鉴权](https://learn.microsoft.com/en-in/azure/ai-services/openai/how-to/managed-identity?view=azureml-api-2)
- [Azure Identity Python 客户端](https://learn.microsoft.com/en-us/python/api/overview/azure/identity-readme?view=azure-python)
- [Azure AI Services 身份认证与角色配置](https://learn.microsoft.com/en-us/azure/ai-services/authentication)
