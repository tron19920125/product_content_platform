import {useCallback, useEffect, useRef, useState} from "react";
import type {PointerEvent as ReactPointerEvent} from "react";
import {mediaUrl, studio} from "./client";
import {Icon} from "./icons";
import type {Layer, Version} from "./types";

const fonts = [{id: "StudioSans", label: "思源黑体"}, {id: "StudioSerif", label: "思源宋体"}, {id: "StudioWenkai", label: "霞鹜文楷"}];
const imageCache = new Map<string, Promise<HTMLImageElement>>();
export function loadImage(url: string) {
  if (!imageCache.has(url)) imageCache.set(url, new Promise((resolve, reject) => {const image = new Image(); image.crossOrigin = "anonymous"; image.onload = () => resolve(image); image.onerror = () => {imageCache.delete(url); reject(new Error("图片加载失败"));}; image.src = mediaUrl(url);}));
  return imageCache.get(url)!;
}
const measure = (context: CanvasRenderingContext2D, value: string, spacing: number) => context.measureText(value).width + Math.max(0, Array.from(value).length - 1) * spacing;
function lines(context: CanvasRenderingContext2D, text: string, width: number, spacing: number) {
  return text.split("\n").flatMap(paragraph => {const result: string[] = []; let current = ""; for (const character of Array.from(paragraph)) {if (current && measure(context, current + character, spacing) > width) {result.push(current); current = character;} else current += character;} result.push(current); return result;});
}
export async function renderComposition(canvas: HTMLCanvasElement, baseUrl: string, layers: Layer[]) {
  await Promise.all(fonts.map(font => document.fonts.load(`16px "${font.id}"`)));
  const base = await loadImage(baseUrl);
  const imageLayers = new Map(await Promise.all(layers.filter(layer => layer.type === "image" && layer.image_url && !layer.hidden).map(async layer => [layer.id, await loadImage(layer.image_url!)] as const)));
  canvas.width = base.naturalWidth; canvas.height = base.naturalHeight;
  const context = canvas.getContext("2d")!; context.clearRect(0, 0, canvas.width, canvas.height); context.drawImage(base, 0, 0);
  for (const layer of layers) {
    if (layer.hidden) continue;
    context.save(); context.translate(layer.x + layer.width / 2, layer.y + layer.height / 2); context.rotate(layer.rotation * Math.PI / 180); context.translate(-layer.width / 2, -layer.height / 2); context.globalAlpha = layer.opacity;
    if (layer.type === "image") {const image = imageLayers.get(layer.id); if (image) context.drawImage(image, 0, 0, layer.width, layer.height);}
    else {
      context.font = `${layer.italic ? "italic " : ""}${layer.bold ? "700" : "400"} ${layer.fontSize}px "${layer.font}"`;
      context.textBaseline = "top"; context.fillStyle = layer.color; context.strokeStyle = layer.strokeColor; context.lineWidth = layer.stroke; context.lineJoin = "round";
      context.shadowColor = "rgba(0,0,0,.35)"; context.shadowBlur = layer.shadow; context.shadowOffsetY = layer.shadow / 3;
      let y = 0;
      for (const line of lines(context, layer.text, layer.width, layer.letterSpacing)) {
        const width = measure(context, line, layer.letterSpacing);
        let x = layer.align === "center" ? (layer.width - width) / 2 : layer.align === "right" ? layer.width - width : 0;
        for (const char of Array.from(line)) {if (layer.stroke) context.strokeText(char, x, y); context.fillText(char, x, y); x += context.measureText(char).width + layer.letterSpacing;}
        y += layer.fontSize * layer.lineHeight;
      }
    }
    context.restore();
  }
}
const newText = (width: number): Layer => ({id: crypto.randomUUID(), type: "text", text: "添加你的文案", x: width * .08, y: width * .08, width: width * .7, height: width * .15, rotation: 0, font: "StudioSans", fontSize: Math.round(width * .048), color: "#182230", bold: true, italic: false, align: "left", lineHeight: 1.3, letterSpacing: 0, stroke: 0, strokeColor: "#ffffff", shadow: 0, opacity: 1, locked: false, hidden: false});

export function Editor({version, onClose, onApplied}: {version: Version; onClose: () => void; onApplied: (value: Version) => void}) {
  const [layers, setLayers] = useState<Layer[]>([]); const layerRef = useRef<Layer[]>([]);
  const [selected, setSelected] = useState<string | null>(null); const [editing, setEditing] = useState<string | null>(null);
  const [size, setSize] = useState({width: 1254, height: 1254}); const [zoom, setZoom] = useState(1);
  const [status, setStatus] = useState("加载编辑数据…"); const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  const [hasSavedDraft, setHasSavedDraft] = useState(false);
  const [undo, setUndo] = useState<Layer[][]>([]); const [redo, setRedo] = useState<Layer[][]>([]);
  const revision = useRef(0); const chain = useRef<Promise<unknown>>(Promise.resolve()); const dirty = useRef(false);
  const canvas = useRef<HTMLCanvasElement>(null); const stage = useRef<HTMLDivElement>(null); const wrapper = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const drag = useRef<{x: number; y: number; initial: Layer[]; layer: Layer; resize: boolean} | null>(null);
  const current = layers.find(layer => layer.id === selected);
  const replace = useCallback((value: Layer[]) => {layerRef.current = value; setLayers(value);}, []);

  useEffect(() => {let live = true; void Promise.all([studio.edit(version.id), loadImage(version.base_url)]).then(([draft, image]) => {if (!live) return; replace(draft.layers); revision.current = draft.revision; setHasSavedDraft(draft.revision > 0); setSize({width: image.naturalWidth, height: image.naturalHeight}); setStatus("已保存");}).catch(value => setError(String(value))); return () => {live = false;};}, [version.id, version.base_url, replace]);
  useEffect(() => {if (!wrapper.current) return; const observer = new ResizeObserver(entries => {const box = entries[0].contentRect; setZoom(Math.min((box.width - 96) / size.width, (box.height - 96) / size.height, 1));}); observer.observe(wrapper.current); return () => observer.disconnect();}, [size]);
  useEffect(() => {let live = true; const buffer = document.createElement("canvas"); void renderComposition(buffer, version.base_url, layers).then(() => {if (live && canvas.current) {canvas.current.width = buffer.width; canvas.current.height = buffer.height; canvas.current.getContext("2d")!.drawImage(buffer, 0, 0);}}).catch(value => setError(String(value))); return () => {live = false;};}, [layers, version.base_url]);

  const save = useCallback(async () => {
    const next = chain.current.catch(() => {}).then(async () => {const snapshot = layerRef.current; setStatus("保存中…"); try {const saved = await studio.saveEdit(version.id, snapshot, revision.current); revision.current = saved.revision; if (snapshot === layerRef.current) {dirty.current = false; setStatus("已保存");} else setStatus("未保存"); return saved;} catch (value) {setStatus("保存失败"); throw value;}});
    chain.current = next; return next;
  }, [version.id]);
  useEffect(() => {if (!dirty.current || drag.current) return; const timer = window.setTimeout(() => {void save().catch(value => setError(String(value)));}, 800); return () => window.clearTimeout(timer);}, [layers, save]);
  function change(value: Layer[], remember = true) {if (remember) {setUndo(old => [...old.slice(-80), structuredClone(layerRef.current)]); setRedo([]);} dirty.current = true; setStatus("未保存"); replace(value);}
  function patch(patch: Partial<Layer>) {if (!current || current.locked) return; change(layers.map(layer => layer.id === current.id ? {...layer, ...patch} : layer));}
  function undoAction() {if (!undo.length) return; const previous = undo[undo.length - 1]; setUndo(undo.slice(0, -1)); setRedo(old => [...old, structuredClone(layers)]); change(previous, false);}
  function redoAction() {if (!redo.length) return; const next = redo[redo.length - 1]; setRedo(redo.slice(0, -1)); setUndo(old => [...old, structuredClone(layers)]); change(next, false);}
  function duplicate() {if (!current) return; const copy = {...current, id: crypto.randomUUID(), x: current.x + 24, y: current.y + 24, locked: false}; change([...layers, copy]); setSelected(copy.id);}
  function remove() {if (current && !current.locked) {change(layers.filter(layer => layer.id !== current.id)); setSelected(null);}}
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if ((event.target as HTMLElement).closest("input,textarea,select,[contenteditable=true]")) return;
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") {event.preventDefault(); event.shiftKey ? redoAction() : undoAction();}
      else if (event.key === "Delete" || event.key === "Backspace") {event.preventDefault(); remove();}
      else if (event.key === "Escape") {setSelected(null); setEditing(null);}
    }; window.addEventListener("keydown", handler); return () => window.removeEventListener("keydown", handler);
  });
  function point(event: ReactPointerEvent) {const rectangle = stage.current!.getBoundingClientRect(); return {x: (event.clientX - rectangle.left) / zoom, y: (event.clientY - rectangle.top) / zoom};}
  function down(event: ReactPointerEvent, layer: Layer, resize = false) {event.stopPropagation(); if (layer.locked || editing) return; const p = point(event); setSelected(layer.id); drag.current = {...p, initial: structuredClone(layers), layer: {...layer}, resize}; event.currentTarget.setPointerCapture(event.pointerId);}
  function move(event: ReactPointerEvent) {if (!drag.current) return; const p = point(event), original = drag.current; const dx = p.x - original.x, dy = p.y - original.y; let updated: Partial<Layer>;
    if (original.resize) {const width = Math.max(30, original.layer.width + dx); updated = {width, height: original.layer.type === "image" ? width * original.layer.height / original.layer.width : Math.max(20, original.layer.height + dy)};}
    else updated = {x: Math.max(-original.layer.width + 20, Math.min(size.width - 20, original.layer.x + dx)), y: Math.max(-original.layer.height + 20, Math.min(size.height - 20, original.layer.y + dy))};
    change(original.initial.map(layer => layer.id === original.layer.id ? {...layer, ...updated} : layer), false);
  }
  function up() {if (!drag.current) return; setUndo(old => [...old.slice(-80), drag.current!.initial]); setRedo([]); drag.current = null; void save().catch(value => setError(String(value)));}
  async function addImage(file: File) {setBusy(true); try {const asset = await studio.upload(file, "style"); const layer = {...newText(size.width), id: crypto.randomUUID(), type: "image" as const, text: "", width: size.width * .3, height: size.width * .3 * asset.height / asset.width, image_url: asset.source_url, asset_id: asset.id}; change([...layers, layer]); setSelected(layer.id);} catch (value) {setError(String(value));} finally {setBusy(false);}}
  async function finish() {setBusy(true); setError(""); try {setEditing(null); const saved = await save(); const rendered = document.createElement("canvas"); await renderComposition(rendered, version.base_url, layerRef.current); const blob = await new Promise<Blob>((resolve, reject) => rendered.toBlob(value => value ? resolve(value) : reject(new Error("画布导出失败")), "image/png")); const asset = await studio.upload(new File([blob], "edited.png", {type: "image/png"}), "style"); const applied = await studio.apply(version.id, saved.revision, asset.id); onApplied(applied);} catch (value) {setError(String(value));} finally {setBusy(false);}}
  async function back() {try {if (dirty.current) await save(); onClose();} catch (value) {setError(`草稿保存失败，暂未退出：${String(value)}`);}}
  const numeric = (key: "fontSize" | "rotation" | "lineHeight" | "letterSpacing" | "stroke" | "shadow", label: string, min: number, max: number, step = 1) => <label>{label}<input type="number" aria-label={label} min={min} max={max} step={step} value={current?.[key] ?? 0} onChange={event => {const value = Number(event.target.value); if (Number.isFinite(value)) patch({[key]: Math.max(min, Math.min(max, value))});}}/></label>;
  return <div className="st-editor"><header className="st-editor-header"><button className="st-secondary" onClick={() => void back()}><Icon name="back" size={18}/>返回工作台</button><div><strong>手动编辑</strong><span>独立文字与图片图层 · 不调用 AI</span></div><span className={status === "保存失败" ? "danger" : "st-muted"}>{status}</span><button className="st-primary" disabled={busy || status === "加载编辑数据…"} onClick={() => void finish()}>{busy ? "保存作品中…" : "完成编辑"}<Icon name="check" size={18}/></button></header>
    {error && <div className="st-alert" role="alert">{error}<button onClick={() => setError("")}>×</button></div>}
    {hasSavedDraft && <div className="st-edit-recovery"><span>已恢复上次编辑草稿，尚未替换当前成图。</span><button className="st-link" onClick={() => setHasSavedDraft(false)}>继续编辑</button><button className="st-link" onClick={() => {void studio.discardEdit(version.id).then(() => {revision.current = 0; replace(version.layers); dirty.current = false; setHasSavedDraft(false); setStatus("已保存");}).catch(value => setError(String(value)));}}>丢弃草稿</button></div>}
    <div className="st-editor-body"><aside className="st-editor-tools"><h3>添加内容</h3><button onClick={() => {const layer = newText(size.width); change([...layers, layer]); setSelected(layer.id); setEditing(layer.id);}}><Icon name="text"/>添加文字</button><button onClick={() => input.current?.click()}><Icon name="image"/>添加图片 / Logo</button><input hidden ref={input} type="file" accept="image/png,image/jpeg,image/webp" onChange={event => {if (event.target.files?.[0]) void addImage(event.target.files[0]); event.target.value = "";}}/><div className="st-section-line"><h3>图层</h3><span>{layers.length}</span></div><div className="st-layer-list">{[...layers].reverse().map(layer => <div key={layer.id} className={selected === layer.id ? "active" : ""}><button className="st-layer-name" onClick={() => setSelected(layer.id)}><Icon name={layer.type === "text" ? "text" : "image"} size={15}/>{layer.type === "text" ? layer.text.slice(0, 9) || "文字" : "图片"}</button><button aria-label={layer.hidden ? "显示图层" : "隐藏图层"} title={layer.hidden ? "显示" : "隐藏"} onClick={() => {if (!layer.locked) change(layers.map(row => row.id === layer.id ? {...row, hidden: !row.hidden} : row));}} style={{opacity: layer.hidden ? .3 : 1}}><Icon name="eye" size={14}/></button><button aria-label={layer.locked ? "解锁图层" : "锁定图层"} onClick={() => change(layers.map(row => row.id === layer.id ? {...row, locked: !row.locked} : row))} style={{opacity: layer.locked ? 1 : .3}}><Icon name="lock" size={14}/></button></div>)}</div><p className="st-muted">原生图片文字不是独立图层。要修改底图中的文字，请返回后使用 AI 修改。</p></aside>
      <main className="st-canvas-wrapper" ref={wrapper}><div className="st-canvas-toolbar"><button title="撤销" aria-label="撤销" disabled={!undo.length} onClick={undoAction}><Icon name="undo" size={18}/></button><button title="重做" aria-label="重做" disabled={!redo.length} onClick={redoAction}><Icon name="redo" size={18}/></button><span>{Math.round(zoom * 100)}%</span><span>{size.width} × {size.height} px</span></div><div className="st-canvas-frame" style={{width: size.width * zoom, height: size.height * zoom}}><div className="st-canvas-stage" ref={stage} style={{width: size.width, height: size.height, transform: `scale(${zoom})`}} onPointerDown={() => {setSelected(null); setEditing(null);}}><canvas ref={canvas}/>{layers.filter(layer => !layer.hidden).map(layer => <div key={layer.id} className={`st-layer-overlay ${selected === layer.id ? "selected" : ""} ${layer.locked ? "locked" : ""}`} style={{left: layer.x, top: layer.y, width: layer.width, height: layer.height, transform: `rotate(${layer.rotation}deg)`, borderWidth: selected === layer.id ? 1.5 / zoom : 0}} onPointerDown={event => down(event, layer)} onPointerMove={move} onPointerUp={up} onDoubleClick={() => {if (layer.type === "text" && !layer.locked) {setSelected(layer.id); setEditing(layer.id);}}}>{editing === layer.id && !layer.locked && <textarea autoFocus aria-label="画布内编辑文字" value={layer.text} onPointerDown={event => event.stopPropagation()} onChange={event => patch({text: event.target.value})} onBlur={() => setEditing(null)} style={{fontFamily: layer.font, fontSize: layer.fontSize, fontWeight: layer.bold ? 700 : 400, fontStyle: layer.italic ? "italic" : "normal", color: layer.color, lineHeight: layer.lineHeight, letterSpacing: layer.letterSpacing, textAlign: layer.align}}/>}{selected === layer.id && !layer.locked && !editing && <button className="st-resize-handle" aria-label="缩放所选对象" style={{width: 10 / zoom, height: 10 / zoom, right: -5 / zoom, bottom: -5 / zoom}} onPointerDown={event => down(event, layer, true)} onPointerMove={move} onPointerUp={up}/>}</div>)}</div></div><p className="st-canvas-hint">双击文字直接编辑 · 拖动调整位置 · 拖动右下角调整文本框/图片大小</p></main>
      <aside className="st-properties"><h3>{current ? current.type === "text" ? "文字属性" : "图片属性" : "对象属性"}</h3>{current ? <><div className="st-object-actions"><button title="复制图层" onClick={duplicate}><Icon name="copy" size={17}/></button><button title="上移图层" disabled={current.locked || layers.indexOf(current) === layers.length - 1} onClick={() => {const rows = [...layers], index = rows.indexOf(current); [rows[index], rows[index + 1]] = [rows[index + 1], rows[index]]; change(rows);}}>↑</button><button title="下移图层" disabled={current.locked || layers.indexOf(current) === 0} onClick={() => {const rows = [...layers], index = rows.indexOf(current); [rows[index], rows[index - 1]] = [rows[index - 1], rows[index]]; change(rows);}}>↓</button><button title="删除图层" disabled={current.locked} onClick={remove}><Icon name="trash" size={17}/></button></div>{current.locked && <p className="st-note">图层已锁定，请在图层列表中解锁。</p>}<fieldset disabled={current.locked}>{current.type === "text" && <><label>内容<textarea rows={3} value={current.text} onChange={event => patch({text: event.target.value})}/></label><label>字体<select value={current.font} onChange={event => patch({font: event.target.value})}>{fonts.map(font => <option key={font.id} value={font.id}>{font.label}</option>)}</select></label><div className="st-property-grid">{numeric("fontSize", "字号", 8, 1024)}<label>颜色<input aria-label="文字颜色" type="color" value={current.color} onChange={event => patch({color: event.target.value})}/></label></div><div className="st-format-row"><button className={current.bold ? "active" : ""} onClick={() => patch({bold: !current.bold})}><b>B</b></button><button className={current.italic ? "active" : ""} onClick={() => patch({italic: !current.italic})}><i>I</i></button><select aria-label="对齐" value={current.align} onChange={event => patch({align: event.target.value as Layer["align"]})}><option value="left">左对齐</option><option value="center">居中</option><option value="right">右对齐</option></select></div><div className="st-property-grid">{numeric("lineHeight", "行距", .5, 4, .1)}{numeric("letterSpacing", "字距", -10, 100)}</div><div className="st-property-grid">{numeric("stroke", "描边", 0, 20)}<label>描边颜色<input type="color" value={current.strokeColor} onChange={event => patch({strokeColor: event.target.value})}/></label></div>{numeric("shadow", "阴影", 0, 80)}</>}{numeric("rotation", "旋转角度", -180, 180)}<label>不透明度<input type="range" min={0} max={1} step={.05} value={current.opacity} onChange={event => patch({opacity: Number(event.target.value)})}/></label></fieldset></> : <div className="st-empty-small"><Icon name="layers" size={28}/><p>选择画布中的对象<br/>或添加一个文字图层</p></div>}<small className="st-font-note">已加载本地字体 · 授权与来源随项目保留。画布预览和导出使用相同渲染器。</small></aside>
    </div>
  </div>;
}
