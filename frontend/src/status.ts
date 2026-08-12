export const STATUS_LABELS: Record<string, string> = {
  draft: "草稿",
  ready: "待开始",
  queued: "排队中",
  running: "进行中",
  planned: "已规划",
  producing: "生产中",
  reviewing: "审核中",
  review: "需复核",
  pass: "通过",
  needs_review: "待审核",
  generated: "已生成",
  approved: "已通过",
  rejected: "已驳回",
  completed: "已完成",
  partial_failed: "部分失败",
  paused: "已暂停",
  failed: "失败",
  archived: "已归档",
  published: "已发布",
  testing: "测试中",
  deprecated: "已停用",
  pending: "待处理",
  dismissed: "已忽略",
};

export function statusLabel(status: string) {
  return STATUS_LABELS[status] ?? status;
}

export function statusTone(status: string) {
  if (["completed", "pass", "approved", "planned", "published"].includes(status)) return "success";
  if (["review", "needs_review", "reviewing", "queued", "partial_failed", "testing"].includes(status)) return "warning";
  if (["failed", "rejected"].includes(status)) return "danger";
  if (["running", "producing"].includes(status)) return "progress";
  return "neutral";
}
