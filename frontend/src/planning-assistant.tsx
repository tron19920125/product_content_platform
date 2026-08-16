import { useMemo, useState } from "react";

import { FeaturePoint, PagePlan, PlanningRun } from "./api";

type PlanningField = "title" | "body" | "visual_goal" | "feature_points";

const FIELDS: Array<{ key: PlanningField; label: string }> = [
  { key: "title", label: "标题" },
  { key: "body", label: "正文" },
  { key: "visual_goal", label: "视觉目标" },
  { key: "feature_points", label: "图文卖点组" },
];

function PlanningValue({ value }: { value: string | FeaturePoint[] | undefined }) {
  if (Array.isArray(value)) return value.length
    ? <span className="planning-feature-value">{value.map((item) => <i key={item.id}><b>{item.title}</b><em>{item.description}</em></i>)}</span>
    : <>（无图文卖点）</>;
  return <>{value || "（空）"}</>;
}

export function PlanningSuggestionPanel({
  run,
  currentPlan,
  applying,
  onApply,
  onClose,
}: {
  run: PlanningRun;
  currentPlan: PagePlan | null;
  applying: boolean;
  onApply: (selectedFields: Record<string, string[]>) => Promise<void>;
  onClose: () => void;
}) {
  const pages = run.suggestion.pages ?? [];
  const currentById = useMemo(() => new Map(currentPlan?.items.map((item) => [item.id, item]) ?? []), [currentPlan]);
  const [selected, setSelected] = useState<Record<string, PlanningField[]>>(() => Object.fromEntries(
    pages.map((page) => [page.key, FIELDS.map((field) => field.key)]),
  ));
  const selectedCount = Object.values(selected).reduce((total, fields) => total + fields.length, 0);

  function toggle(pageKey: string, field: PlanningField) {
    setSelected((current) => {
      const fields = new Set(current[pageKey] ?? []);
      if (fields.has(field)) fields.delete(field); else fields.add(field);
      return { ...current, [pageKey]: Array.from(fields) };
    });
  }

  function selectPage(pageKey: string, checked: boolean) {
    setSelected((current) => ({ ...current, [pageKey]: checked ? FIELDS.map((field) => field.key) : [] }));
  }

  return <div className="planning-suggestion" aria-live="polite">
    <div className="planning-suggestion-head">
      <div>
        <span className="ai-chip">AI 规划建议</span>
        <h4>{run.base_plan_version ? `与当前 V${run.base_plan_version} 对比` : "首版五页文案已生成"}</h4>
        <p>{run.suggestion.set_strategy || "可按页或按字段采用；未勾选的已有内容不会被覆盖。"}</p>
      </div>
      <button className="ghost-button mini" type="button" onClick={onClose}>暂不采用</button>
    </div>
    {run.degraded && <div className="notice warning"><b>已使用可演示降级方案</b><span>LLM 暂时不可用，系统已生成事实安全的确定性文案；你仍可修改或重新规划。</span></div>}
    {(run.suggestion.warnings ?? []).length > 0 && <div className="planning-warnings">{run.suggestion.warnings?.map((warning) => <span key={warning}>{warning}</span>)}</div>}
    <div className="suggestion-page-list">
      {pages.map((page, index) => {
        const current = currentById.get(page.key);
        const pageFields = selected[page.key] ?? [];
        return <article className="suggestion-page" key={page.key}>
          <header>
            <label><input type="checkbox" checked={pageFields.length === FIELDS.length} onChange={(event) => selectPage(page.key, event.target.checked)} />第 {index + 1} 页</label>
            <span>{page.reasoning}</span>
          </header>
          <div className="suggestion-fields">
            {FIELDS.map((field) => <label key={field.key} className={pageFields.includes(field.key) ? "selected" : ""}>
              <input type="checkbox" checked={pageFields.includes(field.key)} onChange={() => toggle(page.key, field.key)} />
              <span>{field.label}</span>
              {current && <small className="before-value"><b>当前</b><PlanningValue value={current[field.key]} /></small>}
              <strong><b>建议</b><PlanningValue value={page[field.key]} /></strong>
            </label>)}
          </div>
          {page.fact_refs.length > 0 && <details><summary>事实来源 {page.fact_refs.length} 项</summary><p>{page.fact_refs.join(" · ")}</p></details>}
        </article>;
      })}
    </div>
    <footer>
      <span>已选择 {selectedCount} 个字段；应用后仍可直接编辑并保存草稿。</span>
      <button className="primary" type="button" disabled={applying || selectedCount === 0} onClick={() => void onApply(selected)}>{applying ? "正在应用…" : `应用所选 ${selectedCount} 项`}</button>
    </footer>
  </div>;
}

export function PlanningRunProgress({ run }: { run: PlanningRun }) {
  const completed = run.status === "completed";
  const failed = run.status === "failed";
  return <div className={`planning-run-progress ${failed ? "failed" : ""}`} role="status" aria-live="polite">
    <span className={completed || failed ? "progress-status-dot" : "spinner"} aria-hidden="true" />
    <div><strong>{failed ? "AI 内容规划失败" : completed ? "AI 内容规划已完成" : run.status === "queued" ? "AI 规划已进入队列" : "LLM 正在规划每页文案"}</strong><small>{failed ? run.error : "正在读取商品事实、参考图和模板约束，生成标题、正文与视觉目标。"}</small></div>
    {!completed && !failed && <div className="indeterminate-track"><i /></div>}
  </div>;
}
