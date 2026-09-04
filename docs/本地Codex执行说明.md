# 本地 Codex 执行说明

新 Studio 把业务状态和模型执行分开：界面负责保存输入快照、拆分任务、保留版本和控制修复次数；Codex 只领取一个明确的生图或质检任务。这样即使执行中断，也不会覆盖旧图或盲目重发。

## 生图与 AI 修改

1. 在界面点击“提交 Codex 生成”。套图会按页面和候选数拆成多个可独立成功、失败或重试的任务。
2. 领取一个任务：

   ```bash
   ./.venv/bin/python scripts/next_codex_job.py
   ```

   输出包含用途、实际目标尺寸、High 质量、生图提示和本地参考图路径。领取后状态为 `running`，不可被另一执行者重复领取。
3. 用 Codex 图片能力按任务包生成或修改图片，再生成一份证据化 `Review` JSON。
4. 保存结果：

   ```bash
   ./.venv/bin/python scripts/complete_codex_job.py <job_id> <image.png> <review.json>
   ```

每张图一完成就会立即出现在界面。分数低于 60 时，后台为该次用户主动生成追加一个 `repair` 任务；修复图再低分也不递归修复。

## 质检重试与手动重检

生图执行结果如未附带有效检查，或用户对“检查未完成”的 AI 底图点击“手动重检”，会进入独立的质检队列。

```bash
./.venv/bin/python scripts/next_codex_review.py
./.venv/bin/python scripts/complete_codex_review.py <task_id> --review <review.json>
```

安全的质检服务异常可记录为失败：

```bash
./.venv/bin/python scripts/complete_codex_review.py <task_id> --error "<失败原因>"
```

系统共尝试三次（首次加两次自动重试）。仍未完成时保留无分数状态，不按 0 分处理，也不触发自动修复。手动编辑版本不允许进入该队列。

## 当前边界

以上脚本是面向当前 Codex 会话的本地执行边界，不是常驻后台 Worker。页面可提交、恢复和展示任务，但在没有 Codex 执行者时不会自行产生新图。当前本地 Studio 不使用 Azure；如后续接入常驻执行器，应继续使用现有任务包与完成接口，不绕过快照、版本、修复次数和结果不明保护。
