import { PointerEvent as ReactPointerEvent, useEffect, useState } from "react";

import { api, Candidate, FontAsset, TextDocument, TextLayer } from "./api";
import { Icon } from "./ui";

type Props = { candidate: Candidate; onComplete: () => Promise<void>; onCancel: () => void };

function FontPreview({ font, active, onSelect }: { font: FontAsset; active: boolean; onSelect: () => void }) {
  const family = `pcp-${font.id}`;
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    let disposed = false;
    const face = new FontFace(family, `url(${api.resolveUrl(font.content_url)})`);
    void face.load().then((ready) => { if (!disposed) { document.fonts.add(ready); setLoaded(true); } }).catch(() => undefined);
    return () => { disposed = true; };
  }, [family, font.content_url]);
  return <button type="button" className={`font-preview-card ${active ? "active" : ""}`} onClick={onSelect}>
    <strong style={{ fontFamily: loaded ? family : "sans-serif" }}>{font.preview}</strong>
    <span>{font.display_name}<small>{font.category} · {font.license}</small></span>
  </button>;
}

function createLayer(index: number): TextLayer {
  return { id: `custom-${crypto.randomUUID()}`, role: "custom", name: `文本框 ${index + 1}`, content: "双击输入文案", box: [.12, .12 + Math.min(index, 5) * .06, .48, .23 + Math.min(index, 5) * .06], font_family: "noto-sans-sc", font_weight: 600, font_size: 72, color: "#181F1C", text_align: "left", vertical_align: "top", line_height: 1.2, letter_spacing: 0, rotation: 0, opacity: 1, stroke_width: 0, stroke_color: "#FFFFFF", shadow: false, shadow_color: "#000000", shadow_blur: 8, shadow_offset_x: 4, shadow_offset_y: 4, background_color: "", background_opacity: 0, padding: 0, visible: true, locked: false, z_index: index, source: "manual", copy_block_id: "" };
}

export function TextLayoutEditor({ candidate, onComplete, onCancel }: Props) {
  const [textDocument, setTextDocument] = useState<TextDocument | null>(null);
  const [fonts, setFonts] = useState<FontAsset[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [instruction, setInstruction] = useState("");
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState("loading");
  const [error, setError] = useState("");
  const composition = candidate.metadata?.composition as Record<string, unknown> | undefined;
  const canvas = Array.isArray(composition?.canvas) ? composition.canvas as number[] : [2048, 2048];
  const selected = textDocument?.layers.find((layer) => layer.id === selectedId);

  useEffect(() => {
    let active = true;
    setBusy("loading");
    void Promise.all([api.getTextDocument(candidate.id), api.listFonts()]).then(([next, fontRows]) => {
      if (!active) return;
      setTextDocument(next); setFonts(fontRows); setSelectedId(next.layers[0]?.id ?? ""); setBusy("");
    }).catch((reason) => { if (active) { setError(reason instanceof Error ? reason.message : "文字图层加载失败"); setBusy(""); } });
    return () => { active = false; };
  }, [candidate.id]);

  function updateLayer(id: string, changes: Partial<TextLayer>) {
    setTextDocument((current) => current ? ({ ...current, layers: current.layers.map((layer) => layer.id === id ? { ...layer, ...changes, source: "manual" } : layer) }) : current);
    setDirty(true);
  }

  function beginTransform(event: ReactPointerEvent, layer: TextLayer, mode: "move" | "resize") {
    if (layer.locked) return;
    event.preventDefault(); event.stopPropagation(); setSelectedId(layer.id);
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

  async function saveDocument(document = textDocument) {
    if (!document) throw new Error("文字图层尚未加载");
    const saved = await api.saveTextDocument(candidate.id, document);
    setTextDocument(saved); setDirty(false); return saved;
  }

  async function perform(action: "save" | "ai" | "apply") {
    setBusy(action); setError("");
    try {
      if (action === "save") await saveDocument();
      if (action === "ai") { if (dirty) await saveDocument(); const planned = await api.aiLayoutTextDocument(candidate.id, instruction); setTextDocument(planned); setSelectedId(planned.layers[0]?.id ?? ""); setDirty(false); }
      if (action === "apply") { const ready = dirty ? await saveDocument() : textDocument; if (!ready) throw new Error("文字图层尚未加载"); await api.applyTextDocument(candidate.id, ready.version); await onComplete(); }
    } catch (reason) { setError(reason instanceof Error ? reason.message : "文字排版操作失败"); } finally { setBusy(""); }
  }

  if (!textDocument) return <div className="typography-editor"><div className="inline-working"><span className="spinner" />正在加载文字图层…</div>{error && <div className="notice error">{error}</div>}</div>;
  return <section className="typography-editor text-layout-editor">
    <div className="tool-heading"><div><strong>文字图层工作台</strong><small>像 PPT 一样增删、拖拽和缩放文本框；应用时只重做透明文字层，不调用生图模型。</small></div><button type="button" className="icon-button" aria-label="关闭文字图层工作台" onClick={onCancel}>×</button></div>
    <div className="ai-layout-bar"><input value={instruction} maxLength={1000} onChange={(event) => setInstruction(event.target.value)} placeholder="可选：描述排版方向，例如“国风书法标题、正文克制留白”"/><button type="button" className="secondary" disabled={!!busy} onClick={() => void perform("ai")}>{busy === "ai" ? "AI 初排中…" : "AI 帮我初排"}</button></div>
    <div className="text-layout-workspace">
      <aside className="text-layer-list"><header><strong>图层</strong><button type="button" onClick={() => { const layer = createLayer(textDocument.layers.length); setTextDocument({ ...textDocument, layers: [...textDocument.layers, layer] }); setSelectedId(layer.id); setDirty(true); }}>＋ 文本框</button></header>{textDocument.layers.map((layer) => <button type="button" key={layer.id} className={layer.id === selectedId ? "active" : ""} onClick={() => setSelectedId(layer.id)}><Icon name="grip"/><span><strong>{layer.name}</strong><small>{layer.content || "空文本"}</small></span><i>{layer.visible ? "●" : "○"}</i></button>)}</aside>
      <div className="text-layout-canvas-wrap"><div className="text-layout-stage" style={{ aspectRatio: `${canvas[0] || 1} / ${canvas[1] || 1}` }} onPointerDown={() => setSelectedId("")}><img src={api.resolveUrl(candidate.base_url)} alt="无营销文字底图" draggable={false}/>{textDocument.layers.map((layer) => <div key={layer.id} className={`editable-text-layer ${layer.id === selectedId ? "selected" : ""} ${layer.locked ? "locked" : ""}`} style={{ left: `${layer.box[0] * 100}%`, top: `${layer.box[1] * 100}%`, width: `${(layer.box[2] - layer.box[0]) * 100}%`, height: `${(layer.box[3] - layer.box[1]) * 100}%`, color: layer.color, opacity: layer.opacity, textAlign: layer.text_align, transform: `rotate(${layer.rotation}deg)`, fontWeight: layer.font_weight, fontSize: `${Math.max(10, layer.font_size / Math.max(canvas[0] / 620, 1))}px`, lineHeight: layer.line_height, letterSpacing: `${layer.letter_spacing}px`, justifyContent: layer.vertical_align === "center" ? "center" : layer.vertical_align === "bottom" ? "flex-end" : "flex-start", display: layer.visible ? "flex" : "none" }} onPointerDown={(event) => beginTransform(event, layer, "move")}><span>{layer.content}</span>{layer.id === selectedId && !layer.locked && <i className="text-resize-handle" onPointerDown={(event) => beginTransform(event, layer, "resize")}/>}</div>)}</div><small>底图预览 · 坐标按比例保存，可适配横版、竖版和正方形。</small></div>
      <aside className="text-property-panel">{selected ? <><header><strong>文本属性</strong><button type="button" className="danger-link" onClick={() => { setTextDocument({ ...textDocument, layers: textDocument.layers.filter((layer) => layer.id !== selected.id) }); setSelectedId(""); setDirty(true); }}>删除</button></header><label><span>图层名称</span><input value={selected.name} onChange={(event) => updateLayer(selected.id, { name: event.target.value })}/></label><label><span>文字内容</span><textarea rows={4} value={selected.content} onChange={(event) => updateLayer(selected.id, { content: event.target.value })}/></label><div className="property-row"><label><span>字号 px</span><input type="number" min="8" max="1024" value={selected.font_size} onChange={(event) => updateLayer(selected.id, { font_size: Number(event.target.value) })}/></label><label><span>粗细</span><select value={selected.font_weight} onChange={(event) => updateLayer(selected.id, { font_weight: Number(event.target.value) })}>{[300,400,500,600,700,800,900].map((weight) => <option key={weight} value={weight}>{weight}</option>)}</select></label></div><div className="property-row"><label><span>颜色</span><input type="color" value={selected.color} onChange={(event) => updateLayer(selected.id, { color: event.target.value.toUpperCase() })}/></label><label><span>旋转</span><input type="number" min="-180" max="180" value={selected.rotation} onChange={(event) => updateLayer(selected.id, { rotation: Number(event.target.value) })}/></label></div><div className="property-row"><label><span>对齐</span><select value={selected.text_align} onChange={(event) => updateLayer(selected.id, { text_align: event.target.value as TextLayer["text_align"] })}><option value="left">左对齐</option><option value="center">居中</option><option value="right">右对齐</option></select></label><label><span>行高</span><input type="number" step="0.05" min="0.6" max="3" value={selected.line_height} onChange={(event) => updateLayer(selected.id, { line_height: Number(event.target.value) })}/></label></div><div className="property-row"><label><span>字距</span><input type="number" min="-20" max="100" value={selected.letter_spacing} onChange={(event) => updateLayer(selected.id, { letter_spacing: Number(event.target.value) })}/></label><label><span>描边</span><input type="number" min="0" max="32" value={selected.stroke_width} onChange={(event) => updateLayer(selected.id, { stroke_width: Number(event.target.value) })}/></label></div><label className="check-control"><input type="checkbox" checked={selected.shadow} onChange={(event) => updateLayer(selected.id, { shadow: event.target.checked })}/>启用阴影</label><label className="check-control"><input type="checkbox" checked={selected.locked} onChange={(event) => updateLayer(selected.id, { locked: event.target.checked })}/>锁定图层</label></> : <div className="empty-property"><Icon name="type"/><strong>选择一个文本框</strong><p>可以编辑文字、字体、大小、颜色、对齐、旋转、描边和阴影。</p></div>}</aside>
    </div>
    {selected && <div className="font-picker"><div><strong>字体库</strong><span>字体名称本身使用对应字体预览；仅展示允许商用并记录许可证的字体。</span></div><div className="font-preview-grid">{fonts.map((font) => <FontPreview key={font.id} font={font} active={selected.font_family === font.id} onSelect={() => updateLayer(selected.id, { font_family: font.id })}/>)}</div></div>}
    {textDocument.ai_reasoning && <p className="tool-note"><strong>AI 初排说明：</strong>{textDocument.ai_reasoning}</p>}
    {busy && <div className="inline-working" role="status"><span className="spinner" />{{ loading: "加载中", save: "保存版本中", ai: "AI 正在初排", apply: "正在确定性渲染文字层" }[busy]}…</div>}
    {error && <div className="notice error">{error}</div>}
    <div className="tool-actions"><span>文字文档 v{textDocument.version}{dirty ? " · 有未保存修改" : " · 已保存"}</span><button type="button" className="ghost-button" disabled={!!busy || !dirty} onClick={() => void perform("save")}>保存草稿</button><button type="button" className="primary" disabled={!!busy} onClick={() => void perform("apply")}>{busy === "apply" ? "应用中…" : "应用排版"}</button></div>
  </section>;
}
