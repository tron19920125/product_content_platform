import { FormEvent, useEffect, useMemo, useState } from "react";

import { api, Candidate, ProductionSnapshot, TypographySettings } from "./api";

type TypographyEditorProps = {
  projectId: string;
  pageId: string;
  candidate: Candidate;
  onComplete: () => Promise<void>;
  onCancel: () => void;
};

type TypographyFormState = {
  fontFamily: TypographySettings["font_family"];
  titleFontSize: string;
  bodyFontSize: string;
  titleColor: string;
  bodyColor: string;
  autoTitleColor: boolean;
  autoBodyColor: boolean;
  textAlign: TypographySettings["text_align"];
  verticalAlign: TypographySettings["vertical_align"];
  offsetX: string;
  offsetY: string;
  titleLineSpacing: string;
  bodyLineSpacing: string;
  titleBodyGap: string;
};

const asRecord = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" ? value as Record<string, unknown> : {};

const asString = (value: unknown, fallback = "") =>
  typeof value === "string" ? value : fallback;

const optionalNumber = (value: string) => value.trim() === "" ? undefined : Number(value);

function initialTypography(candidate: Candidate): TypographyFormState {
  const composition = asRecord(candidate.metadata?.composition);
  const overrides = asRecord(composition.typography_overrides);
  const titleColor = asString(overrides.title_color, asString(composition.title_color, "#181F1C"));
  const bodyColor = asString(overrides.body_color, asString(composition.body_color, "#37413C"));
  return {
    fontFamily: asString(overrides.font_family, asString(composition.font_family, "system_sans")) as TypographySettings["font_family"],
    titleFontSize: overrides.title_font_size === undefined ? "" : String(overrides.title_font_size),
    bodyFontSize: overrides.body_font_size === undefined ? "" : String(overrides.body_font_size),
    titleColor,
    bodyColor,
    autoTitleColor: overrides.title_color === undefined,
    autoBodyColor: overrides.body_color === undefined,
    textAlign: asString(overrides.text_align, asString(composition.text_align, "left")) as TypographySettings["text_align"],
    verticalAlign: asString(overrides.vertical_align, asString(composition.vertical_align, "top")) as TypographySettings["vertical_align"],
    offsetX: String(overrides.offset_x ?? composition.offset_x ?? 0),
    offsetY: String(overrides.offset_y ?? composition.offset_y ?? 0),
    titleLineSpacing: overrides.title_line_spacing === undefined ? "" : String(overrides.title_line_spacing),
    bodyLineSpacing: overrides.body_line_spacing === undefined ? "" : String(overrides.body_line_spacing),
    titleBodyGap: overrides.title_body_gap === undefined ? "" : String(overrides.title_body_gap),
  };
}

export function TypographyEditor({ projectId, pageId, candidate, onComplete, onCancel }: TypographyEditorProps) {
  const [form, setForm] = useState<TypographyFormState>(() => initialTypography(candidate));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const composition = asRecord(candidate.metadata?.composition);
  const update = <Key extends keyof TypographyFormState>(key: Key, value: TypographyFormState[Key]) =>
    setForm((current) => ({ ...current, [key]: value }));

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const typography: TypographySettings = {
      font_family: form.fontFamily,
      title_font_size: optionalNumber(form.titleFontSize),
      body_font_size: optionalNumber(form.bodyFontSize),
      title_color: form.autoTitleColor ? undefined : form.titleColor,
      body_color: form.autoBodyColor ? undefined : form.bodyColor,
      text_align: form.textAlign,
      vertical_align: form.verticalAlign,
      offset_x: Number(form.offsetX || 0),
      offset_y: Number(form.offsetY || 0),
      title_line_spacing: optionalNumber(form.titleLineSpacing),
      body_line_spacing: optionalNumber(form.bodyLineSpacing),
      title_body_gap: optionalNumber(form.titleBodyGap),
    };
    try {
      await api.recomposePage(projectId, pageId, candidate.id, typography);
      await onComplete();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "重新排版失败");
    } finally {
      setBusy(false);
    }
  }

  return <form className="typography-editor" onSubmit={submit}>
    <div className="tool-heading">
      <div><strong>文字排版设置</strong><small>只重做透明文字层并重新质检，不会再次调用生图模型。</small></div>
      <button type="button" className="icon-button" aria-label="关闭文字排版设置" onClick={onCancel}>×</button>
    </div>
    <div className="typography-grid">
      <label><span>字体风格</span><select value={form.fontFamily} onChange={(event) => update("fontFamily", event.target.value as TypographySettings["font_family"])}><option value="system_sans">现代无衬线</option><option value="system_bold">粗体无衬线</option><option value="system_serif">衬线字体</option></select></label>
      <label><span>标题字号</span><input type="number" min="24" max="512" placeholder={`自动 · 当前 ${composition.title_font_size ?? "-"} px`} value={form.titleFontSize} onChange={(event) => update("titleFontSize", event.target.value)} /></label>
      <label><span>正文字号</span><input type="number" min="16" max="320" placeholder={`自动 · 当前 ${composition.body_font_size ?? "-"} px`} value={form.bodyFontSize} onChange={(event) => update("bodyFontSize", event.target.value)} /></label>
      <label><span>横向对齐</span><select value={form.textAlign} onChange={(event) => update("textAlign", event.target.value as TypographySettings["text_align"])}><option value="left">左对齐</option><option value="center">居中</option><option value="right">右对齐</option></select></label>
      <label><span>纵向位置</span><select value={form.verticalAlign} onChange={(event) => update("verticalAlign", event.target.value as TypographySettings["vertical_align"])}><option value="top">顶部</option><option value="center">居中</option><option value="bottom">底部</option></select></label>
      <label><span>水平偏移（px）</span><input type="number" min="-512" max="512" value={form.offsetX} onChange={(event) => update("offsetX", event.target.value)} /></label>
      <label><span>垂直偏移（px）</span><input type="number" min="-512" max="512" value={form.offsetY} onChange={(event) => update("offsetY", event.target.value)} /></label>
      <label><span>标题行距（px）</span><input type="number" min="0" max="128" placeholder="自动" value={form.titleLineSpacing} onChange={(event) => update("titleLineSpacing", event.target.value)} /></label>
      <label><span>正文行距（px）</span><input type="number" min="0" max="128" placeholder="自动" value={form.bodyLineSpacing} onChange={(event) => update("bodyLineSpacing", event.target.value)} /></label>
      <label><span>标题正文间距（px）</span><input type="number" min="0" max="256" placeholder="自动" value={form.titleBodyGap} onChange={(event) => update("titleBodyGap", event.target.value)} /></label>
    </div>
    <div className="color-controls">
      <label className="color-control"><span>标题颜色</span><input type="color" value={form.titleColor} disabled={form.autoTitleColor} onChange={(event) => update("titleColor", event.target.value)} /><input type="text" value={form.titleColor} disabled={form.autoTitleColor} pattern="#[0-9A-Fa-f]{6}" onChange={(event) => update("titleColor", event.target.value)} /><i><input type="checkbox" checked={form.autoTitleColor} onChange={(event) => update("autoTitleColor", event.target.checked)} />自动对比色</i></label>
      <label className="color-control"><span>正文颜色</span><input type="color" value={form.bodyColor} disabled={form.autoBodyColor} onChange={(event) => update("bodyColor", event.target.value)} /><input type="text" value={form.bodyColor} disabled={form.autoBodyColor} pattern="#[0-9A-Fa-f]{6}" onChange={(event) => update("bodyColor", event.target.value)} /><i><input type="checkbox" checked={form.autoBodyColor} onChange={(event) => update("autoBodyColor", event.target.checked)} />自动对比色</i></label>
    </div>
    <p className="tool-note">空白字号和间距表示继续使用自动适配。若文字可能溢出，系统会在模板文字区内自动缩小或收回偏移，不会静默裁切。</p>
    {busy && <div className="inline-working" role="status"><span className="spinner" />正在重新生成文字层并执行质检…</div>}
    {error && <div className="notice error">{error}</div>}
    <div className="tool-actions"><button type="button" className="ghost-button" disabled={busy} onClick={onCancel}>取消</button><button type="submit" className="primary" disabled={busy}>{busy ? "重新排版中…" : "应用并重新排版"}</button></div>
  </form>;
}

type StitchComposerProps = {
  projectId: string;
  snapshot: ProductionSnapshot;
  disabled?: boolean;
};

type StitchItem = {
  id: string;
  pageOrder: number;
  pageTitle: string;
  candidateIndex: number;
  url: string;
  size: [number, number];
};

function candidateSize(candidate: Candidate): [number, number] {
  const composition = asRecord(candidate.metadata?.composition);
  const canvas = composition.canvas;
  return Array.isArray(canvas) && canvas.length === 2 && canvas.every((value) => typeof value === "number")
    ? [Number(canvas[0]), Number(canvas[1])]
    : [0, 0];
}

export function StitchComposer({ projectId, snapshot, disabled = false }: StitchComposerProps) {
  const items = useMemo<StitchItem[]>(() => snapshot.pages.flatMap((row) => row.candidates.map((candidate) => ({
    id: candidate.id,
    pageOrder: row.page.order,
    pageTitle: row.page.title,
    candidateIndex: candidate.candidate_index,
    url: api.resolveUrl(candidate.composed_url),
    size: candidateSize(candidate),
  }))), [snapshot.pages]);
  const defaultIds = useMemo(() => snapshot.pages.flatMap((row) => {
    const preferred = row.candidates.find((candidate) => candidate.id === row.decision?.candidate_id) ?? row.candidates[0];
    return preferred ? [preferred.id] : [];
  }), [snapshot.pages]);
  const itemMap = useMemo(() => new Map(items.map((item) => [item.id, item])), [items]);
  const optionIds = useMemo(() => new Set(items.map((item) => item.id)), [items]);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [direction, setDirection] = useState<"vertical" | "horizontal">("vertical");
  const [alignment, setAlignment] = useState<"start" | "center" | "end">("center");
  const [gap, setGap] = useState(0);
  const [backgroundColor, setBackgroundColor] = useState("#FFFFFF");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [downloadUrl, setDownloadUrl] = useState("");

  useEffect(() => {
    setSelectedIds((current) => {
      if (current.some((id) => !optionIds.has(id))) return defaultIds;
      return current.length > 0 ? current : defaultIds;
    });
  }, [defaultIds, optionIds]);

  const selected = selectedIds.flatMap((id) => {
    const item = itemMap.get(id);
    return item ? [item] : [];
  });
  const projectedSize = selected.length === 0 ? [0, 0] : direction === "vertical"
    ? [Math.max(...selected.map((item) => item.size[0])), selected.reduce((total, item) => total + item.size[1], 0) + gap * (selected.length - 1)]
    : [selected.reduce((total, item) => total + item.size[0], 0) + gap * (selected.length - 1), Math.max(...selected.map((item) => item.size[1]))];

  function toggle(id: string) {
    setDownloadUrl("");
    setSelectedIds((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  }

  function move(id: string, delta: -1 | 1) {
    setDownloadUrl("");
    setSelectedIds((current) => {
      const index = current.indexOf(id);
      const target = index + delta;
      if (index < 0 || target < 0 || target >= current.length) return current;
      const next = [...current];
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  }

  async function exportLongImage() {
    setBusy(true);
    setError("");
    setDownloadUrl("");
    try {
      const result = await api.stitchProject(projectId, {
        candidate_ids: selectedIds,
        direction,
        gap,
        background_color: backgroundColor,
        alignment,
      });
      setDownloadUrl(api.resolveUrl(result.download_url));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "长图拼接失败");
    } finally {
      setBusy(false);
    }
  }

  if (items.length < 2) return null;
  return <section className="stitch-composer">
    <div className="tool-heading"><div><strong>长图拼接与导出</strong><small>勾选任意候选图、调整顺序后，按原始分辨率无损拼接成 PNG。</small></div><b>{selected.length} 张已选</b></div>
    <div className="stitch-layout">
      <div>
        <span className="tool-label">选择图片</span>
        <div className="stitch-picker">{items.map((item) => <label key={item.id} className={selectedIds.includes(item.id) ? "selected" : ""}><input type="checkbox" checked={selectedIds.includes(item.id)} disabled={disabled || busy} onChange={() => toggle(item.id)} /><img src={item.url} alt={`第 ${item.pageOrder} 页候选 ${item.candidateIndex}`} /><span>第 {item.pageOrder} 页 · 候选 {item.candidateIndex}<small>{item.pageTitle}</small></span></label>)}</div>
      </div>
      <div className="stitch-order-panel">
        <span className="tool-label">拼接顺序</span>
        {selected.length === 0 ? <p>请至少选择 2 张图片。</p> : <ol>{selected.map((item, index) => <li key={item.id}><b>{index + 1}</b><img src={item.url} alt="" /><span>第 {item.pageOrder} 页 · 候选 {item.candidateIndex}</span><button type="button" aria-label="上移" disabled={index === 0 || busy} onClick={() => move(item.id, -1)}>↑</button><button type="button" aria-label="下移" disabled={index === selected.length - 1 || busy} onClick={() => move(item.id, 1)}>↓</button></li>)}</ol>}
      </div>
    </div>
    <div className="stitch-options">
      <label><span>方向</span><select value={direction} disabled={busy} onChange={(event) => { setDirection(event.target.value as typeof direction); setDownloadUrl(""); }}><option value="vertical">纵向长图</option><option value="horizontal">横向拼接</option></select></label>
      <label><span>对齐</span><select value={alignment} disabled={busy} onChange={(event) => { setAlignment(event.target.value as typeof alignment); setDownloadUrl(""); }}><option value="start">起始边</option><option value="center">居中</option><option value="end">结束边</option></select></label>
      <label><span>图片间距（px）</span><input type="number" min="0" max="128" value={gap} disabled={busy} onChange={(event) => { setGap(Number(event.target.value)); setDownloadUrl(""); }} /></label>
      <label><span>间距背景色</span><div className="inline-color"><input type="color" value={backgroundColor} disabled={busy} onChange={(event) => { setBackgroundColor(event.target.value); setDownloadUrl(""); }} /><code>{backgroundColor.toUpperCase()}</code></div></label>
      <div className="projected-size"><span>预计尺寸</span><strong>{projectedSize[0] || "-"} × {projectedSize[1] || "-"} px</strong></div>
    </div>
    {busy && <div className="inline-working" role="status"><span className="spinner" />正在按原始分辨率拼接并导出 PNG…</div>}
    {error && <div className="notice error">{error}</div>}
    {downloadUrl && <div className="stitch-result"><img src={downloadUrl} alt="长图拼接结果预览" /><div><strong>长图已生成</strong><span>{projectedSize[0]} × {projectedSize[1]} px · PNG</span><a className="primary" href={downloadUrl} download>下载长图 PNG</a></div></div>}
    <div className="tool-actions"><button type="button" className="primary" disabled={disabled || busy || selected.length < 2} onClick={() => void exportLongImage()}>{busy ? "拼接中…" : "生成并导出长图"}</button></div>
  </section>;
}
