import { useState } from "react";

import { api, Candidate } from "./api";

export function CandidateEditPanel({
  candidate,
  disabled,
  onSubmitted,
  onCancel,
}: {
  candidate: Candidate;
  disabled: boolean;
  onSubmitted: () => Promise<void>;
  onCancel: () => void;
}) {
  const [instruction, setInstruction] = useState("");
  const [quality, setQuality] = useState(String((candidate.metadata?.effective_generation as { quality?: string } | undefined)?.quality ?? "high"));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit() {
    setBusy(true); setError("");
    try {
      await api.editCandidate(candidate.id, instruction, quality);
      await onSubmitted();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "单图修改提交失败");
    } finally { setBusy(false); }
  }

  return <div className="candidate-edit-panel">
    <header><div><strong>继续修改此图</strong><small>只处理这个候选，不会重新生成其他页面。</small></div><button className="ghost-button mini" type="button" onClick={onCancel}>取消</button></header>
    <div className="candidate-edit-source"><img src={api.resolveUrl(candidate.base_url)} alt="本次编辑使用的无字底图" /><p><b>实际输入</b>当前候选的无营销文字 base.png；系统同时附带原商品参考图，并在生成后重新排版文字、仅质检本页。</p></div>
    <label><span>新增视觉要求</span><textarea rows={4} maxLength={1000} value={instruction} onChange={(event) => setInstruction(event.target.value)} placeholder="例如：保持商品角度和构图不变，把窗外改成清晨氛围，增加柔和侧光和地面反射。" /></label>
    <div className="candidate-edit-tips"><span>适合：背景、场景、光影、材质、角度、视觉效果</span><span>文字内容/字号/颜色请使用“调整文字排版”</span></div>
    <div className="candidate-edit-actions"><label>生成质量<select value={quality} onChange={(event) => setQuality(event.target.value)}><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option></select></label><button className="primary" type="button" disabled={disabled || busy || instruction.trim().length < 3} onClick={() => void submit()}>{busy ? "正在提交…" : "仅重新生成此图"}</button></div>
    {busy && <div className="planning-run-progress" role="status"><span className="spinner" /><div><strong>正在创建单图修改任务</strong><small>提交后页面会显示实时编辑与质检进度。</small></div></div>}
    {error && <div className="notice error">{error}</div>}
  </div>;
}

export function CandidateHistory({ history, currentId }: { history: Candidate[]; currentId: string }) {
  if (history.length <= 1) return null;
  const rows = [...history].sort((a, b) => a.created_at.localeCompare(b.created_at));
  return <details className="candidate-history"><summary>查看修改历史（{rows.length} 个版本）</summary><div>
    {rows.map((item, index) => {
      const sourceId = String((item.metadata?.source_candidate_id as string | undefined) ?? "");
      return <article key={item.id} className={item.id === currentId ? "current" : ""}>
        <img src={api.resolveUrl(item.composed_url)} alt={`版本 ${index + 1}`} />
        <p><b>V{index + 1}{item.id === currentId ? " · 当前" : ""}</b><span>{sourceId ? `源自 ${sourceId.slice(0, 8)}` : "初始生成"}</span><small>{String((item.metadata?.user_instruction as string | undefined) ?? "")}</small></p>
      </article>;
    })}
  </div></details>;
}
