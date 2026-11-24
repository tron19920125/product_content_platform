import {ReviewFindings, reviewDisplayText} from "./WorkspacePanels";
import {Icon} from "./icons";
import type {Review, ReviewTask} from "./types";

export function DesignReview({review, task, busy, repairPending, selectedActions, onToggleAction, onRecheck, onRepair}: {
  review: Review; task?: ReviewTask; busy: boolean; repairPending: boolean;
  selectedActions: string[]; onToggleAction: (action: string) => void; onRecheck: () => void; onRepair: () => void;
}) {
  const checking = review.status === "checking" || task?.status === "queued" || task?.status === "running";
  const completed = review.status === "completed" && !checking;
  const actions = review.findings.filter(item => item.kind !== "uncertain" && item.action?.trim());
  return <section className="st-design-review" aria-label="AI 设计点评">
    <div className="st-section-line"><h3>AI 设计点评</h3><span className="st-review-badge">{checking ? "点评中" : completed ? "点评完成" : "待点评"}</span></div>
    {completed ? <>
      <p className="st-review-summary">{reviewDisplayText(review.summary || review.note)}</p>
      {!!review.strengths?.length && <div className="st-review-strengths"><h4>值得保留</h4><ul>{review.strengths.map((value, index) => <li key={index}>{value}</li>)}</ul></div>}
      {review.copy_observation && <div className="st-review-copy"><h4>文案核对</h4><p>{review.copy_observation}</p></div>}
      <ReviewFindings review={review} selectedActions={selectedActions} onToggleAction={onToggleAction}/>
      {actions.length > 0 && <div className="st-review-repair"><button className="st-primary" disabled={busy || repairPending} onClick={onRepair}><Icon name="spark" size={17}/>{repairPending ? "修复已提交" : "按点评修复"}</button><p>优先执行本次填写的修改要求，采用兼容的点评建议生成新版本，保留原图。</p></div>}
    </> : <div className="st-review-state" role="status"><p>{checking ? "正在点评当前图片，你可以继续查看、编辑和下载。" : review.note || "这张图片还没有设计点评，可点击下方按钮开始。"}</p></div>}
    <button className="st-link" disabled={busy || checking || repairPending} onClick={onRecheck}>{checking ? "等待点评完成" : completed ? "重新点评" : "开始点评"}</button>
  </section>;
}
