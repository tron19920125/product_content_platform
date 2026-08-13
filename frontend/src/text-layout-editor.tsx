import { PointerEvent as ReactPointerEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api, Candidate, FontAsset, TextDocument, TextLayer } from "./api";
import { Icon } from "./ui";

type Props = { candidate: Candidate; onComplete: () => Promise<void>; onCancel: () => void };
type InspectorView = "properties" | "fonts";
type FontLoadState = "idle" | "loading" | "loaded" | "error" | "unavailable";

const RECENT_FONT_KEY = "pcp:text-editor:recent-fonts:v1";
const SYSTEM_FONT_FAMILIES: Record<string, string> = {
  system_sans: '"Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", sans-serif',
  system_bold: '"Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", sans-serif',
  system_serif: 'SimSun, "Songti SC", "Noto Serif CJK SC", serif',
};

function readRecentFonts(): string[] {
  try {
    const value = JSON.parse(window.localStorage.getItem(RECENT_FONT_KEY) ?? "[]");
    return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string").slice(0, 6) : [];
  } catch { return []; }
}

function FontPreview({ font, active, state, family, previewText, onVisible, onSelect }: {
  font: FontAsset;
  active: boolean;
  state: FontLoadState;
  family: string;
  previewText: string;
  onVisible: () => void;
  onSelect: () => void;
}) {
  const cardRef = useRef<HTMLButtonElement>(null);
  const disabled = state === "error" || state === "unavailable";
  useEffect(() => {
    const card = cardRef.current;
    if (!card || disabled || state !== "idle") return;
    const observer = new IntersectionObserver(([entry]) => { if (entry.isIntersecting) onVisible(); }, { rootMargin: "80px" });
    observer.observe(card);
    return () => observer.disconnect();
  }, [disabled, onVisible, state]);
  return <button ref={cardRef} type="button" disabled={disabled} className={`font-preview-card ${active ? "active" : ""} ${state}`} onClick={onSelect} aria-pressed={active}>
    <strong lang={font.coverage.startsWith("拉丁") ? "en" : "zh-CN"} style={{ fontFamily: state === "loaded" ? family : "sans-serif" }}>{previewText}</strong>
    <span>{font.display_name}<small>{font.category} · {font.coverage}</small></span>
    <em>{state === "loaded" ? "OFL 许可已核验" : state === "loading" ? "正在载入预览…" : state === "unavailable" ? "字体文件未安装" : state === "error" ? "字体加载失败" : "滚动到此处加载"}</em>
  </button>;
}

function createLayer(index: number): TextLayer {
  return {
    id: `custom-${crypto.randomUUID()}`, role: "custom", name: `文本框 ${index + 1}`, content: "双击输入文案",
    box: [.12, .12 + Math.min(index, 5) * .06, .48, .23 + Math.min(index, 5) * .06],
    font_family: "noto-sans-sc", font_weight: 600, font_style: "normal", underline: false, strikethrough: false,
    font_size: 72, color: "#181F1C", text_align: "left", vertical_align: "top", line_height: 1.2,
    letter_spacing: 0, rotation: 0, opacity: 1, stroke_width: 0, stroke_color: "#FFFFFF", shadow: false,
    shadow_color: "#000000", shadow_blur: 8, shadow_offset_x: 4, shadow_offset_y: 4, background_color: "",
    background_opacity: 0, padding: 0, visible: true, locked: false, z_index: index, source: "manual", copy_block_id: "",
  };
}

function styleDefaults(layer: TextLayer): TextLayer {
  return { ...layer, font_style: layer.font_style ?? "normal", underline: layer.underline ?? false, strikethrough: layer.strikethrough ?? false };
}

export function TextLayoutEditor({ candidate, onComplete, onCancel }: Props) {
  const [textDocument, setTextDocument] = useState<TextDocument | null>(null);
  const [fonts, setFonts] = useState<FontAsset[]>([]);
  const [fontStates, setFontStates] = useState<Record<string, FontLoadState>>({});
  const [selectedId, setSelectedId] = useState("");
  const [inspectorView, setInspectorView] = useState<InspectorView>("properties");
  const [fontSearch, setFontSearch] = useState("");
  const [fontCategory, setFontCategory] = useState("全部");
  const [recentFonts, setRecentFonts] = useState<string[]>(readRecentFonts);
  const [instruction, setInstruction] = useState("");
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState("loading");
  const [error, setError] = useState("");
  const [feedback, setFeedback] = useState("");
  const [sourceSize, setSourceSize] = useState<[number, number] | null>(null);
  const [stageSize, setStageSize] = useState<[number, number]>([0, 0]);
  const fontLoadStarted = useRef(new Set<string>());
  const stageRef = useRef<HTMLDivElement>(null);
  const composition = candidate.metadata?.composition as Record<string, unknown> | undefined;
  const generated = candidate.metadata?.generator as Record<string, unknown> | undefined;
  const requestedSize = String(generated?.actual_size ?? generated?.size ?? generated?.requested_size ?? "");
  const requestedCanvas = requestedSize.match(/^(\d+)x(\d+)$/i);
  const metadataCanvas = Array.isArray(composition?.canvas) ? composition.canvas as number[] : requestedCanvas ? [Number(requestedCanvas[1]), Number(requestedCanvas[2])] : [2048, 2048];
  const canvas = sourceSize ?? metadataCanvas;
  const stageScale = stageSize[0] && stageSize[1]
    ? Math.min(stageSize[0] / Math.max(canvas[0], 1), stageSize[1] / Math.max(canvas[1], 1))
    : Math.min(620 / Math.max(canvas[0], 1), 580 / Math.max(canvas[1], 1));
  const selected = textDocument?.layers.find((layer) => layer.id === selectedId);
  const selectedFont = fonts.find((font) => font.id === selected?.font_family);

  useEffect(() => {
    let active = true;
    setBusy("loading");
    setSourceSize(null);
    void Promise.all([api.getTextDocument(candidate.id), api.listFonts()]).then(([next, fontRows]) => {
      if (!active) return;
      const normalized = { ...next, layers: next.layers.map(styleDefaults) };
      setTextDocument(normalized);
      setFonts(fontRows);
      setFontStates(Object.fromEntries(fontRows.map((font) => [font.id, font.preview_available ? "idle" : "unavailable"])) as Record<string, FontLoadState>);
      setSelectedId(normalized.layers[0]?.id ?? "");
      setBusy("");
    }).catch((reason) => { if (active) { setError(reason instanceof Error ? reason.message : "文字图层加载失败"); setBusy(""); } });
    return () => { active = false; };
  }, [candidate.id]);

  const fontFamilies = useMemo(() => ({ ...SYSTEM_FONT_FAMILIES, ...Object.fromEntries(fonts.map((font) => [font.id, `"pcp-${font.id}", sans-serif`])) }), [fonts]);
  const fontCategories = useMemo(() => ["全部", "最近", ...Array.from(new Set(fonts.map((font) => font.category)))], [fonts]);
  const displayFonts = useMemo(() => {
    const query = fontSearch.trim().toLowerCase();
    return fonts
      .filter((font) => fontCategory === "全部" || (fontCategory === "最近" ? recentFonts.includes(font.id) : font.category === fontCategory))
      .filter((font) => !query || [font.name, font.display_name, font.category, font.coverage, ...(font.tags ?? [])].some((value) => value.toLowerCase().includes(query)))
      .sort((left, right) => {
        if (fontCategory === "最近") return recentFonts.indexOf(left.id) - recentFonts.indexOf(right.id);
        return Number(right.preview_available) - Number(left.preview_available) || left.display_name.localeCompare(right.display_name, "zh-CN");
      });
  }, [fontCategory, fontSearch, fonts, recentFonts]);

  const loadFont = useCallback((font: FontAsset) => {
    if (!font.preview_available || fontLoadStarted.current.has(font.id)) return;
    fontLoadStarted.current.add(font.id);
    setFontStates((current) => ({ ...current, [font.id]: "loading" }));
    const family = `pcp-${font.id}`;
    const face = new FontFace(family, `url("${api.resolveUrl(font.content_url)}") format("truetype")`, { weight: "100 900" });
    void face.load().then((ready) => {
      document.fonts.add(ready);
      setFontStates((current) => ({ ...current, [font.id]: "loaded" }));
    }).catch(() => setFontStates((current) => ({ ...current, [font.id]: "error" })));
  }, []);

  useEffect(() => { if (selectedFont) loadFont(selectedFont); }, [loadFont, selectedFont]);
  useEffect(() => {
    const stage = stageRef.current;
    if (!stage) return;
    const update = () => {
      const bounds = stage.getBoundingClientRect();
      const next: [number, number] = [bounds.width, bounds.height];
      setStageSize((current) => current[0] === next[0] && current[1] === next[1] ? current : next);
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(stage);
    return () => observer.disconnect();
  }, [canvas[0], canvas[1]]);
  useEffect(() => {
    const closeFontLibrary = (event: KeyboardEvent) => { if (event.key === "Escape" && inspectorView === "fonts") setInspectorView("properties"); };
    window.addEventListener("keydown", closeFontLibrary);
    return () => window.removeEventListener("keydown", closeFontLibrary);
  }, [inspectorView]);

  function updateLayer(id: string, changes: Partial<TextLayer>) {
    setTextDocument((current) => current ? ({ ...current, layers: current.layers.map((layer) => layer.id === id ? { ...layer, ...changes, source: "manual" } : layer) }) : current);
    setDirty(true);
  }

  function selectFont(font: FontAsset) {
    if (!selected) return;
    loadFont(font);
    updateLayer(selected.id, { font_family: font.id });
    setRecentFonts((current) => {
      const next = [font.id, ...current.filter((id) => id !== font.id)].slice(0, 6);
      window.localStorage.setItem(RECENT_FONT_KEY, JSON.stringify(next));
      return next;
    });
  }

  function beginTransform(event: ReactPointerEvent, layer: TextLayer, mode: "move" | "resize") {
    if (layer.locked) return;
    event.preventDefault(); event.stopPropagation(); setSelectedId(layer.id); setInspectorView("properties");
    const stage = event.currentTarget.closest(".text-layout-stage")?.getBoundingClientRect();
    if (!stage) return;
    const startX = event.clientX; const startY = event.clientY; const start = [...layer.box] as TextLayer["box"];
    const move = (pointer: PointerEvent) => {
      const dx = (pointer.clientX - startX) / stage.width; const dy = (pointer.clientY - startY) / stage.height;
      if (mode === "resize") updateLayer(layer.id, { box: [start[0], start[1], Math.min(.99, Math.max(start[0] + .03, start[2] + dx)), Math.min(.99, Math.max(start[1] + .03, start[3] + dy))] });
      else { const width = start[2] - start[0]; const height = start[3] - start[1]; const x = Math.min(1 - width, Math.max(0, start[0] + dx)); const y = Math.min(1 - height, Math.max(0, start[1] + dy)); updateLayer(layer.id, { box: [x, y, x + width, y + height] }); }
    };
    const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
    window.addEventListener("pointermove", move); window.addEventListener("pointerup", up);
  }

  async function saveDocument(documentValue = textDocument) {
    if (!documentValue) throw new Error("文字图层尚未加载");
    const saved = await api.saveTextDocument(candidate.id, documentValue);
    setTextDocument({ ...saved, layers: saved.layers.map(styleDefaults) }); setDirty(false); return saved;
  }

  async function perform(action: "save" | "ai" | "apply") {
    setBusy(action); setError(""); setFeedback("");
    try {
      if (action === "save") { const saved = await saveDocument(); setFeedback(`文字文档 v${saved.version} 已保存。`); }
      if (action === "ai") {
        if (dirty) await saveDocument();
        const planned = await api.aiLayoutTextDocument(candidate.id, instruction);
        setTextDocument({ ...planned, layers: planned.layers.map(styleDefaults) });
        setSelectedId(planned.layers[0]?.id ?? "");
        setInspectorView("properties");
        setDirty(false);
        setFeedback(`AI 已生成新的排版方案 v${planned.version}；画布已更新，确认后请点击“应用排版”。`);
      }
      if (action === "apply") { const ready = dirty ? await saveDocument() : textDocument; if (!ready) throw new Error("文字图层尚未加载"); await api.applyTextDocument(candidate.id, ready.version); await onComplete(); }
    } catch (reason) { setError(reason instanceof Error ? reason.message : "文字排版操作失败"); } finally { setBusy(""); }
  }

  if (!textDocument) return <div className="typography-editor"><div className="inline-working"><span className="spinner" />正在加载文字图层…</div>{error && <div className="notice error">{error}</div>}</div>;
  return <section className="typography-editor text-layout-editor">
    <div className="tool-heading"><div><strong>文字图层工作台</strong><small>像 PPT 一样增删、拖拽和缩放文本框；应用时只重做透明文字层，不调用生图模型。</small></div><button type="button" className="icon-button" aria-label="关闭文字图层工作台" onClick={onCancel}>×</button></div>
    <div className="ai-layout-bar"><input value={instruction} maxLength={1000} onChange={(event) => setInstruction(event.target.value)} placeholder="可选：描述排版方向，例如“国风书法标题、正文克制留白”；留空则生成另一版方案"/><button type="button" className="secondary" disabled={!!busy} onClick={() => void perform("ai")}>{busy === "ai" ? "AI 排版中…" : "AI 帮我重新排"}</button></div>
    <div className="text-layout-workspace">
      <aside className="text-layer-list"><header><strong>图层</strong><button type="button" onClick={() => { const layer = createLayer(textDocument.layers.length); setTextDocument({ ...textDocument, layers: [...textDocument.layers, layer] }); setSelectedId(layer.id); setInspectorView("properties"); setDirty(true); }}>＋ 文本框</button></header>{textDocument.layers.map((layer) => <button type="button" key={layer.id} className={layer.id === selectedId ? "active" : ""} onClick={() => { setSelectedId(layer.id); setInspectorView("properties"); }}><Icon name="grip"/><span><strong>{layer.name}</strong><small>{layer.content || "空文本"}</small></span><i>{layer.visible ? "●" : "○"}</i></button>)}</aside>
      <div className="text-layout-canvas-wrap"><div ref={stageRef} className="text-layout-stage" style={{ aspectRatio: `${canvas[0] || 1} / ${canvas[1] || 1}` }} onPointerDown={() => { setSelectedId(""); setInspectorView("properties"); }}><img src={api.resolveUrl(candidate.base_url)} alt="无营销文字底图" draggable={false} onLoad={(event) => { const image = event.currentTarget; setSourceSize([image.naturalWidth || 1, image.naturalHeight || 1]); }}/>{textDocument.layers.map((layer) => { const stroke = layer.stroke_width ? Math.max(.5, layer.stroke_width * stageScale) : 0; const shadow = layer.shadow ? `${layer.shadow_offset_x * stageScale}px ${layer.shadow_offset_y * stageScale}px ${Math.max(1, layer.shadow_blur * stageScale)}px ${layer.shadow_color}` : "none"; const decoration = [layer.underline ? "underline" : "", layer.strikethrough ? "line-through" : ""].filter(Boolean).join(" ") || "none"; return <div key={layer.id} className={`editable-text-layer ${layer.id === selectedId ? "selected" : ""} ${layer.locked ? "locked" : ""}`} style={{ left: `${layer.box[0] * 100}%`, top: `${layer.box[1] * 100}%`, width: `${(layer.box[2] - layer.box[0]) * 100}%`, height: `${(layer.box[3] - layer.box[1]) * 100}%`, color: layer.color, opacity: layer.opacity, textAlign: layer.text_align, transform: `rotate(${layer.rotation}deg)`, fontFamily: fontFamilies[layer.font_family], fontWeight: layer.font_weight, fontStyle: layer.font_style, textDecorationLine: decoration, fontSize: `${Math.max(4, layer.font_size * stageScale)}px`, lineHeight: layer.line_height, letterSpacing: `${layer.letter_spacing * stageScale}px`, WebkitTextStroke: `${stroke}px ${layer.stroke_color}`, paintOrder: "stroke fill", textShadow: shadow, justifyContent: layer.vertical_align === "center" ? "center" : layer.vertical_align === "bottom" ? "flex-end" : "flex-start", display: layer.visible ? "flex" : "none" }} onPointerDown={(event) => beginTransform(event, layer, "move")}><span>{layer.content}</span>{layer.id === selectedId && !layer.locked ? <i className="text-resize-handle" onPointerDown={(event) => beginTransform(event, layer, "resize")}/> : null}</div>; })}</div><small>{sourceSize ? `${sourceSize[0]} × ${sourceSize[1]} · ` : ""}底图按原始比例缩放 · 字体、字形和效果实时显示；坐标按比例保存。</small></div>
      <aside className={`text-property-panel ${inspectorView === "fonts" ? "font-library-view" : ""}`}>
        {selected && inspectorView === "fonts" ? <>
          <header className="font-library-header"><button type="button" className="font-library-back" onClick={() => setInspectorView("properties")}>‹ 文本属性</button><strong>选择字体</strong></header>
          <label className="font-search"><span className="sr-only">搜索字体</span><input autoFocus value={fontSearch} onChange={(event) => setFontSearch(event.target.value)} placeholder="搜索字体、风格或用途" /></label>
          <div className="font-category-tabs" role="tablist" aria-label="字体分类">{fontCategories.map((category) => <button type="button" role="tab" aria-selected={fontCategory === category} className={fontCategory === category ? "active" : ""} key={category} onClick={() => setFontCategory(category)}>{category}</button>)}</div>
          <div className="font-license-note"><strong>可商用开源字体</strong><span>仅展示许可证已核验且允许随软件再分发的字体。</span></div>
          <div className="font-preview-grid">{displayFonts.length ? displayFonts.map((font) => <FontPreview key={font.id} font={font} active={selected.font_family === font.id} state={fontStates[font.id] ?? "idle"} family={fontFamilies[font.id]} previewText={font.coverage.startsWith("拉丁") ? font.preview : (selected.content.trim().slice(0, 18) || font.preview)} onVisible={() => loadFont(font)} onSelect={() => selectFont(font)}/>) : <p className="font-empty">没有匹配的字体</p>}</div>
        </> : selected ? <>
          <header><strong>文本属性</strong><button type="button" className="danger-link" onClick={() => { setTextDocument({ ...textDocument, layers: textDocument.layers.filter((layer) => layer.id !== selected.id) }); setSelectedId(""); setDirty(true); }}>删除</button></header>
          <label><span>图层名称</span><input value={selected.name} onChange={(event) => updateLayer(selected.id, { name: event.target.value })}/></label>
          <label><span>文字内容</span><textarea rows={4} value={selected.content} onChange={(event) => updateLayer(selected.id, { content: event.target.value })}/></label>
          <button type="button" className="font-family-trigger" onClick={() => setInspectorView("fonts")} aria-label="打开字体库"><span style={{ fontFamily: fontStates[selected.font_family] === "loaded" ? fontFamilies[selected.font_family] : undefined }}>{selectedFont?.display_name ?? selected.font_family}</span><small>{selectedFont?.category ?? "字体"}</small><b>›</b></button>
          <div className="format-toolbar" aria-label="文字样式">
            <button type="button" className={selected.font_weight >= 700 ? "active" : ""} aria-label="加粗" aria-pressed={selected.font_weight >= 700} onClick={() => updateLayer(selected.id, { font_weight: selected.font_weight >= 700 ? 400 : 700 })}><strong>B</strong></button>
            <button type="button" className={selected.font_style === "italic" ? "active" : ""} aria-label="斜体" aria-pressed={selected.font_style === "italic"} onClick={() => updateLayer(selected.id, { font_style: selected.font_style === "italic" ? "normal" : "italic" })}><i>I</i></button>
            <button type="button" className={selected.underline ? "active" : ""} aria-label="下划线" aria-pressed={selected.underline} onClick={() => updateLayer(selected.id, { underline: !selected.underline })}><u>U</u></button>
            <button type="button" className={selected.strikethrough ? "active" : ""} aria-label="删除线" aria-pressed={selected.strikethrough} onClick={() => updateLayer(selected.id, { strikethrough: !selected.strikethrough })}><s>S</s></button>
            <span className="font-size-stepper"><button type="button" aria-label="减小字号" onClick={() => updateLayer(selected.id, { font_size: Math.max(8, selected.font_size - 2) })}>−</button><input aria-label="字号" type="number" min="8" max="1024" value={selected.font_size} onChange={(event) => updateLayer(selected.id, { font_size: Number(event.target.value) })}/><button type="button" aria-label="增大字号" onClick={() => updateLayer(selected.id, { font_size: Math.min(1024, selected.font_size + 2) })}>＋</button></span>
          </div>
          <div className="property-row"><label><span>颜色</span><input type="color" value={selected.color} onChange={(event) => updateLayer(selected.id, { color: event.target.value.toUpperCase() })}/></label><label><span>对齐</span><select value={selected.text_align} onChange={(event) => updateLayer(selected.id, { text_align: event.target.value as TextLayer["text_align"] })}><option value="left">左对齐</option><option value="center">居中</option><option value="right">右对齐</option></select></label></div>
          <details className="advanced-text-properties"><summary>更多排版与效果</summary><div className="property-row"><label><span>粗细</span><select value={selected.font_weight} onChange={(event) => updateLayer(selected.id, { font_weight: Number(event.target.value) })}>{[300,400,500,600,700,800,900].map((weight) => <option key={weight} value={weight}>{weight}</option>)}</select></label><label><span>旋转</span><input type="number" min="-180" max="180" value={selected.rotation} onChange={(event) => updateLayer(selected.id, { rotation: Number(event.target.value) })}/></label></div><div className="property-row"><label><span>行高</span><input type="number" step="0.05" min="0.6" max="3" value={selected.line_height} onChange={(event) => updateLayer(selected.id, { line_height: Number(event.target.value) })}/></label><label><span>字距</span><input type="number" min="-20" max="100" value={selected.letter_spacing} onChange={(event) => updateLayer(selected.id, { letter_spacing: Number(event.target.value) })}/></label></div><div className="property-row"><label><span>描边宽度 px</span><input type="number" min="0" max="32" value={selected.stroke_width} onChange={(event) => updateLayer(selected.id, { stroke_width: Number(event.target.value) })}/></label><label><span>描边颜色</span><input type="color" value={selected.stroke_color} onChange={(event) => updateLayer(selected.id, { stroke_color: event.target.value.toUpperCase() })}/></label></div><label className="check-control"><input type="checkbox" checked={selected.shadow} onChange={(event) => updateLayer(selected.id, { shadow: event.target.checked })}/>启用阴影</label></details>
          <label className="check-control"><input type="checkbox" checked={selected.locked} onChange={(event) => updateLayer(selected.id, { locked: event.target.checked })}/>锁定图层</label>
        </> : <div className="empty-property"><Icon name="type"/><strong>选择一个文本框</strong><p>选择后可直接设置字体、字号、加粗、斜体、颜色、描边和其他排版效果。</p></div>}
      </aside>
    </div>
    {textDocument.ai_reasoning && <p className="tool-note"><strong>AI 初排说明：</strong>{textDocument.ai_reasoning}</p>}
    {busy && <div className="inline-working" role="status"><span className="spinner" />{{ loading: "加载中", save: "保存版本中", ai: "AI 正在初排", apply: "正在确定性渲染文字层" }[busy]}…</div>}
    {feedback && <div className="notice success" role="status">{feedback}</div>}
    {error && <div className="notice error">{error}</div>}
    <div className="tool-actions"><span>文字文档 v{textDocument.version}{dirty ? " · 有未保存修改" : " · 已保存"}</span><button type="button" className="ghost-button" disabled={!!busy || !dirty} onClick={() => void perform("save")}>保存草稿</button><button type="button" className="primary" disabled={!!busy} onClick={() => void perform("apply")}>{busy === "apply" ? "应用中…" : "应用排版"}</button></div>
  </section>;
}
