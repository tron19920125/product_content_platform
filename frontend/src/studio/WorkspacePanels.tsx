import {useEffect, useRef, useState} from "react";
import type {ReactNode} from "react";
import {freshPage} from "./client";
import {Icon} from "./icons";
import type {Catalog, Content, Page, Review} from "./types";

/** A keyboard-operable action menu shared by page and history actions. */
export function ActionMenu({label, children}: {label: string; children: ReactNode}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  function close(restore = false) {setOpen(false); if (restore) trigger.current?.focus();}
  useEffect(() => {
    if (!open) return;
    root.current?.querySelector<HTMLButtonElement>('[role="menuitem"]:not(:disabled)')?.focus();
    const outside = (event: PointerEvent) => {if (!root.current?.contains(event.target as Node)) setOpen(false);};
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, [open]);
  return <div className="st-action-menu" ref={root} onBlur={event => {if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);}}>
    <button ref={trigger} className="st-icon" aria-label={label} aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)}>⋯</button>
    {open && <div className="st-menu-panel" role="menu" aria-label={label} onClick={event => {if ((event.target as HTMLElement).closest('button:not(:disabled)')) close(true);}} onKeyDown={event => {
      const items = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('button:not(:disabled)'));
      const index = items.indexOf(document.activeElement as HTMLButtonElement);
      if (event.key === "Escape") {event.preventDefault(); event.stopPropagation(); close(true);}
      if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
        event.preventDefault();
        items[event.key === "Home" ? 0 : event.key === "End" ? items.length - 1 : (index + (event.key === "ArrowDown" ? 1 : -1) + items.length) % items.length]?.focus();
      }
    }}>{children}</div>}
  </div>;
}

export function PagePurposes({content, config, sizes, onChange}: {content: Content; config?: Catalog["tools"][number]; sizes: Catalog["sizes"]; onChange: (pages: Page[]) => void}) {
  const [removed, setRemoved] = useState<{page: Page; index: number} | null>(null);
  const add = useRef<HTMLSelectElement>(null);
  const maximum = config?.max_pages ?? 15;
  function move(index: number, direction: number) {
    const pages = [...content.pages];
    [pages[index], pages[index + direction]] = [pages[index + direction], pages[index]];
    onChange(pages);
  }
  return <section className="st-page-strip" aria-label={content.tool === "a_plus_detail" ? "详情模块设置" : "图片用途设置"}>
    <div className="st-section-line"><strong>{content.tool === "a_plus_detail" ? "详情模块" : "图片用途"}</strong><span>已添加 {content.pages.length} 张 / 最多 {maximum} 张</span>
      <select ref={add} aria-label="添加页面用途" value="" onChange={event => {if (event.target.value) onChange([...content.pages, freshPage(event.target.value)]);}} disabled={content.pages.length >= maximum}><option value="">＋ 添加{content.tool === "a_plus_detail" ? "模块" : "图片"}</option>{config?.purposes.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}</select>
    </div>
    <div className="st-page-pills">{content.pages.map((page, index) => <div key={page.id} className={`st-purpose-card ${page.skipped ? "skipped" : ""}`}>
      <div className="st-purpose-heading"><span className="st-purpose-number">{index + 1}</span><strong>{config?.purposes.find(p => p.id === page.purpose)?.label ?? page.purpose}</strong>{page.output && <span className="st-custom-size">单独设置</span>}
        <ActionMenu label={`第 ${index + 1} 页更多操作`}><button role="menuitem" aria-label={`上移第 ${index + 1} 页`} disabled={index === 0} onClick={() => move(index, -1)}>↑ 上移</button><button role="menuitem" aria-label={`下移第 ${index + 1} 页`} disabled={index === content.pages.length - 1} onClick={() => move(index, 1)}>↓ 下移</button><button role="menuitem" className="danger" aria-label={`移除第 ${index + 1} 页`} disabled={content.pages.length <= 1} onClick={() => {setRemoved({page, index}); onChange(content.pages.filter(p => p.id !== page.id)); add.current?.focus();}}>移除图片</button></ActionMenu>
      </div>
      <label className="st-purpose-size"><span>尺寸</span><select aria-label={`第 ${index + 1} 页输出尺寸`} value={page.output ? `${page.output.ratio}|${page.output.resolution}` : ""} onChange={event => {
        const [ratio, resolution] = event.target.value.split("|");
        onChange(content.pages.map(row => row.id === page.id ? {...row, output: event.target.value ? {ratio, resolution} : null} : row));
      }}><option value="">跟随整组 · {content.output.ratio} · {content.output.resolution.toUpperCase()}</option>{sizes.map(size => <option key={`${size.ratio}-${size.resolution}`} value={`${size.ratio}|${size.resolution}`}>{size.ratio} · {size.resolution.toUpperCase()} · {size.width} × {size.height} px</option>)}</select></label>
    </div>)}</div>
    {removed && <div className="st-page-undo" role="status"><span>已移除“{config?.purposes.find(p => p.id === removed.page.purpose)?.label ?? "图片"}”</span><button className="st-link" disabled={content.pages.length >= maximum} onClick={() => {const pages = [...content.pages]; pages.splice(Math.min(removed.index, pages.length), 0, removed.page); onChange(pages); setRemoved(null);}}>撤销移除</button></div>}
  </section>;
}

export function PlanEditor({content, config, onChange}: {content: Content; config?: Catalog["tools"][number]; onChange: (pages: Page[]) => void}) {
  const [selected, setSelected] = useState(content.pages[0]?.id);
  const active = content.pages.find(page => page.id === selected) ?? content.pages[0];
  if (!active) return null;
  const index = content.pages.indexOf(active);
  const update = (patch: Partial<Page>) => onChange(content.pages.map(page => page.id === active.id ? {...page, ...patch} : page));
  return <div className="st-plan-grid">
    <nav className="st-module-list" aria-label="模块目录">{content.pages.map((page, i) => <button key={page.id} aria-current={active.id === page.id ? "true" : undefined} className={active.id === page.id ? "active" : ""} onClick={() => setSelected(page.id)}><span>{String(i + 1).padStart(2, "0")}</span><div><strong>{config?.purposes.find(value => value.id === page.purpose)?.label}</strong><small>{page.title || "待填写标题"}</small></div><Icon name="chevron" size={16}/></button>)}</nav>
    <article className="st-module-editor"><div className="st-section-line"><strong>模块 {index + 1} · {config?.purposes.find(value => value.id === active.purpose)?.label}</strong><span>{index + 1} / {content.pages.length}</span></div>
      <label className="st-field">标题<input aria-label={`模块 ${index + 1} 标题`} placeholder="模块标题" value={active.title} onChange={event => update({title: event.target.value})}/></label>
      <label className="st-field">正文 <small>可留空</small><textarea aria-label={`模块 ${index + 1} 文案`} placeholder="图片中的正文，可留空" rows={4} value={active.body} onChange={event => update({body: event.target.value})}/></label>
      <label className="st-field">画面描述<textarea aria-label={`模块 ${index + 1} 画面描述`} placeholder="画面内容与构图" rows={4} value={active.visual_goal} onChange={event => update({visual_goal: event.target.value})}/></label>
      <div className="st-module-pagination"><button className="st-secondary small" disabled={index === 0} onClick={() => setSelected(content.pages[index - 1].id)}>上一个模块</button><button className="st-secondary small" disabled={index === content.pages.length - 1} onClick={() => setSelected(content.pages[index + 1].id)}>下一个模块</button></div>
    </article>
  </div>;
}

export function ReviewFindings({review}: {review: Review}) {
  const labels: Record<string, string> = {error: "明确问题", uncertain: "待确认", suggestion: "优化建议"};
  return <div className="st-review-findings">{Object.entries(labels).map(([kind, label]) => {
    const findings = review.findings.filter(finding => finding.kind === kind);
    if (!findings.length) return null;
    return <details key={kind} open={kind !== "suggestion"} className={`st-review-group ${kind}`}><summary>{label}<span>{findings.length} 项</span></summary>{findings.map((finding, index) => <div className="st-finding" key={index}><p>{finding.message}</p>{finding.evidence && <span>依据：{finding.evidence}</span>}</div>)}</details>;
  })}{review.status === "completed" && !review.findings.length && <p className="st-note">本次检查未报告问题。</p>}</div>;
}
