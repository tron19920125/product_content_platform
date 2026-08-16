import { CSSProperties, FormEvent, PointerEvent as ReactPointerEvent, ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api, ImageCapabilities, LayoutLibrary, TemplateDefinition } from "./api";
import { Icon, IconButton } from "./ui";

type BoxKey = "safe_area_box" | "product_box" | "product_anchor_box";
type RegionKey = BoxKey | `text:${string}` | `feature:${string}`;
type Box = [number, number, number, number];

const PAGE_TYPES = [
  ["hero", "主视觉"],
  ["selling_point", "核心卖点"],
  ["function", "功能说明"],
  ["scene", "生活场景"],
  ["parameters", "商品参数"],
] as const;

const EDITOR_PRODUCT_ASSET = "/api/candidates/showcase-square-2048-candidate-1/files/base";

const regionStyle = (box: Box) => ({
  left: `${box[0] * 100}%`, top: `${box[1] * 100}%`,
  width: `${(box[2] - box[0]) * 100}%`, height: `${(box[3] - box[1]) * 100}%`,
});

const clamp = (value: number, minimum: number, maximum: number) => Math.min(maximum, Math.max(minimum, value));
const snapEdge = (value: number, targets: number[], threshold: number) => {
  const match = targets.reduce<{ value: number; distance: number } | null>((best, target) => {
    const distance = Math.abs(target - value);
    return distance <= threshold && (!best || distance < best.distance) ? { value: target, distance } : best;
  }, null);
  return match?.value ?? value;
};
const snapPosition = (value: number, size: number, targets: number[], threshold: number) => {
  const points = [value, value + size / 2, value + size];
  let bestAdjustment = 0;
  let bestDistance = Number.POSITIVE_INFINITY;
  points.forEach((point) => targets.forEach((target) => {
    const adjustment = target - point;
    const distance = Math.abs(adjustment);
    if (distance <= threshold && distance < bestDistance) { bestAdjustment = adjustment; bestDistance = distance; }
  }));
  return value + bestAdjustment;
};

function pageTypeLabel(value: string) {
  return PAGE_TYPES.find(([key]) => key === value)?.[1] ?? value;
}

function ratioLabel(library: LayoutLibrary) {
  const divisor = (a: number, b: number): number => b ? divisor(b, a % b) : a;
  const common = divisor(library.width, library.height);
  return `${library.width / common}:${library.height / common}`;
}

export function LayoutCenter() {
  const [libraries, setLibraries] = useState<LayoutLibrary[]>([]);
  const [templates, setTemplates] = useState<TemplateDefinition[]>([]);
  const [capabilities, setCapabilities] = useState<ImageCapabilities | null>(null);
  const [selectedLibraryId, setSelectedLibraryId] = useState("");
  const [editing, setEditing] = useState<TemplateDefinition | null>(null);
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [showLibraryForm, setShowLibraryForm] = useState(false);
  const [libraryName, setLibraryName] = useState("");
  const [libraryDescription, setLibraryDescription] = useState("");
  const [librarySize, setLibrarySize] = useState("2048x2048");
  const [pendingDelete, setPendingDelete] = useState<TemplateDefinition | null>(null);

  const refresh = async (preferredLibrary = selectedLibraryId) => {
    const [libraryRows, templateRows, imageCapabilities] = await Promise.all([
      api.listLayoutLibraries(), api.listTemplates(undefined, true), api.getImageCapabilities(),
    ]);
    setLibraries(libraryRows);
    setTemplates(templateRows);
    setCapabilities(imageCapabilities);
    setSelectedLibraryId(preferredLibrary || libraryRows[0]?.id || "");
  };

  useEffect(() => { void refresh(); }, []);

  const selectedLibrary = libraries.find((row) => row.id === selectedLibraryId) ?? libraries[0];
  const libraryTemplates = useMemo(
    () => templates.filter((row) => row.library_id === selectedLibrary?.id).sort((a, b) => a.name.localeCompare(b.name) || b.version - a.version),
    [templates, selectedLibrary],
  );

  const createLibrary = async (event: FormEvent) => {
    event.preventDefault();
    setBusy("library"); setMessage("");
    try {
      const created = await api.createLayoutLibrary({ name: libraryName, size: librarySize, description: libraryDescription });
      setShowLibraryForm(false); setLibraryName(""); setLibraryDescription("");
      await refresh(created.id);
      setMessage("版式库已创建。现在可以在库中设计页面模板。");
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "版式库创建失败");
    } finally { setBusy(""); }
  };

  const createTemplate = async () => {
    if (!selectedLibrary) return;
    setBusy("template"); setMessage("");
    try {
      const draft = await api.createTemplateDraft(selectedLibrary.id, {
        name: "未命名页面模板",
        page_types: ["hero"],
        scene_prompt_hint: selectedLibrary.width > selectedLibrary.height
          ? "生成适合横向叙事的真实高端空间，保留文字区域的低细节负空间"
          : selectedLibrary.width < selectedLibrary.height
            ? "生成适合竖向故事海报的真实高端空间，保留文字区域的低细节负空间"
            : "生成具有真实空间层次、自然光和克制陈设的高端商品场景",
      });
      await refresh(selectedLibrary.id);
      setEditing(draft);
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "模板创建失败");
    } finally { setBusy(""); }
  };

  const editTemplate = async (template: TemplateDefinition) => {
    if (template.status === "draft") { setEditing(template); return; }
    setBusy(`version-${template.id}`); setMessage("");
    try {
      const version = await api.createTemplateVersion(template.id);
      await refresh(template.library_id);
      setEditing(version);
      setMessage(`已从 V${template.version} 创建 V${version.version} 草稿；旧版本保持不变。`);
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "新版本创建失败");
    } finally { setBusy(""); }
  };

  const deleteDraft = async (template: TemplateDefinition) => {
    setPendingDelete(null);
    setBusy(`delete-${template.id}`); setMessage("");
    try {
      await api.deleteTemplateDraft(template.id);
      await refresh(template.library_id);
      setMessage(`已删除“${template.name}”V${template.version} 草稿，已发布版本保持不变。`);
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "草稿删除失败");
    } finally { setBusy(""); }
  };

  return <section className="layout-center">
    <header className="section-heading layout-center-heading">
      <div><h3>版式库</h3><p>一个版式库固定一个画布尺寸；库内页面模板共享输出规格，便于整套生产与长图拼接。</p></div>
      <button className="primary" onClick={() => setShowLibraryForm((value) => !value)}>＋ 新建版式库</button>
    </header>
    {showLibraryForm && <form className="layout-library-form" onSubmit={createLibrary}>
      <label>版式库名称<input required value={libraryName} onChange={(event) => setLibraryName(event.target.value)} placeholder="例如：横版 4K 家电叙事" /></label>
      <label>固定画布尺寸<select value={librarySize} onChange={(event) => setLibrarySize(event.target.value)}>
        {(capabilities?.size_presets ?? []).map((item) => <option key={item.value} value={item.value}>{item.label} · {item.value}{item.experimental ? "（实验性）" : ""}</option>)}
      </select></label>
      <label className="wide">说明<input value={libraryDescription} onChange={(event) => setLibraryDescription(event.target.value)} placeholder="说明适用渠道、品类或内容风格" /></label>
      <button className="primary" disabled={busy === "library"}>{busy === "library" ? "创建中…" : "创建版式库"}</button>
    </form>}
    {message && <div className="notice">{message}</div>}
    <div className="layout-library-grid">
      {libraries.map((library) => <button key={library.id} className={`layout-library-card ${selectedLibrary?.id === library.id ? "active" : ""}`} onClick={() => setSelectedLibraryId(library.id)}>
        <span className="library-canvas-icon" style={{ aspectRatio: `${library.width} / ${library.height}` }}><i /><b /></span>
        <strong>{library.name}</strong>
        <span>{library.size} · {ratioLabel(library)}</span>
        <small>{library.template_count} 个已发布模板 · {library.is_builtin ? "系统示例" : "自定义"}</small>
      </button>)}
    </div>

    {selectedLibrary && <section className="layout-library-detail">
      <header className="section-heading">
        <div><p className="eyebrow">{selectedLibrary.size} · {ratioLabel(selectedLibrary)}</p><h3>{selectedLibrary.name}</h3><p>{selectedLibrary.description || "尚未填写版式库说明。"}</p></div>
        <button className="primary" disabled={busy === "template"} onClick={() => void createTemplate()}>{busy === "template" ? "创建中…" : "＋ 新建页面模板"}</button>
      </header>
      <div className="layout-template-grid">
        {libraryTemplates.map((template) => <article key={template.id} className="layout-template-card">
          <TemplateMiniature template={template} />
          <div className="layout-template-meta">
            <div><strong>{template.name}</strong><span className={`template-state ${template.status}`}>{template.status === "published" ? `已发布 V${template.version}` : `草稿 V${template.version}`}</span></div>
            <p>{template.page_types.map(pageTypeLabel).join(" / ")}</p>
            <div className="template-card-actions"><button className="secondary" disabled={busy === `version-${template.id}`} onClick={() => void editTemplate(template)}>{template.status === "published" ? "创建新版本并编辑" : "继续编辑"}</button>{template.status === "draft" && <button className="ghost-button danger" disabled={busy === `delete-${template.id}`} onClick={() => setPendingDelete(template)}>{busy === `delete-${template.id}` ? "删除中…" : "删除草稿"}</button>}</div>
          </div>
        </article>)}
      </div>
    </section>}

    {editing && selectedLibrary && <TemplateEditor
      template={editing}
      library={libraries.find((row) => row.id === editing.library_id) ?? selectedLibrary}
      onClose={() => setEditing(null)}
      onSaved={async (next, published) => {
        await refresh(next.library_id);
        setEditing(published ? null : next);
        setMessage(published ? `${next.name} V${next.version} 已发布，可在项目和配方中使用。` : "模板草稿已保存。");
      }}
    />}
    {pendingDelete && <div className="confirm-backdrop" role="presentation"><section className="confirm-dialog" role="alertdialog" aria-modal="true" aria-labelledby="delete-template-title"><Icon name="alert" size={28}/><div><h3 id="delete-template-title">删除模板草稿？</h3><p>将删除“{pendingDelete.name}”V{pendingDelete.version} 草稿。已发布版本不会受影响，此操作无法撤销。</p></div><div className="confirm-actions"><button className="secondary" autoFocus onClick={() => setPendingDelete(null)}>取消</button><button className="danger-button" onClick={() => void deleteDraft(pendingDelete)}>确认删除</button></div></section></div>}
  </section>;
}

function TemplateMiniature({ template }: { template: TemplateDefinition }) {
  return <div className="layout-miniature" style={{ aspectRatio: `${template.width} / ${template.height}` }}>
    <div className="mini-environment" />
    {template.text_slots.map((slot) => <div key={slot.id} className={`mini-box ${slot.role === "headline" ? "title" : "body"}`} style={regionStyle(slot.box)}><span>{slot.name}</span></div>)}
    {template.feature_slots.map((slot) => <div key={slot.id} className="mini-box feature" style={regionStyle(slot.box)}><span>{slot.name}</span></div>)}
    <div className="mini-box allowed" style={regionStyle(template.product_box)} />
    <div className="mini-product" style={regionStyle(template.product_anchor_box)}><img src={api.resolveUrl(EDITOR_PRODUCT_ASSET)} alt="" /></div>
    <small>{template.size}</small>
  </div>;
}

type ResizeHandle = "nw" | "n" | "ne" | "e" | "se" | "s" | "sw" | "w";
type Interaction = { key: RegionKey; mode: "move" | ResizeHandle; startX: number; startY: number; box: Box; before: TemplateDefinition };

function TemplateEditor({ template, library, onClose, onSaved }: { template: TemplateDefinition; library: LayoutLibrary; onClose: () => void; onSaved: (next: TemplateDefinition, published: boolean) => Promise<void> }) {
  const [draft, setDraft] = useState(template);
  const [activeKey, setActiveKey] = useState<RegionKey>(`text:${template.text_slots[0]?.id ?? "headline"}`);
  const [interaction, setInteraction] = useState<Interaction | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [zoom, setZoom] = useState(75);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [isPanning, setIsPanning] = useState(false);
  const [spacePressed, setSpacePressed] = useState(false);
  const [history, setHistory] = useState<TemplateDefinition[]>([template]);
  const [historyIndex, setHistoryIndex] = useState(0);
  const [savedAt, setSavedAt] = useState<Date | null>(null);
  const [savedSnapshot, setSavedSnapshot] = useState(template);
  const dirty = JSON.stringify(draft) !== JSON.stringify(savedSnapshot);
  const [confirmClose, setConfirmClose] = useState(false);
  const canvasRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const panStart = useRef({ x: 0, y: 0, originX: 0, originY: 0 });

  useEffect(() => { setDraft(template); setHistory([template]); setHistoryIndex(0); setSavedSnapshot(template); }, [template]);

  const commit = useCallback((next: TemplateDefinition) => {
    setDraft(next);
    setHistory((current) => [...current.slice(0, historyIndex + 1), next].slice(-100));
    setHistoryIndex((current) => Math.min(current + 1, 99));
  }, [historyIndex]);

  const undo = useCallback(() => {
    if (historyIndex <= 0) return;
    const next = historyIndex - 1; setHistoryIndex(next); setDraft(history[next]);
  }, [history, historyIndex]);
  const redo = useCallback(() => {
    if (historyIndex >= history.length - 1) return;
    const next = historyIndex + 1; setHistoryIndex(next); setDraft(history[next]);
  }, [history, historyIndex]);

  const getBox = useCallback((source: TemplateDefinition, key: RegionKey): Box => {
    if (key.startsWith("text:")) return source.text_slots.find((slot) => slot.id === key.slice(5))?.box ?? source.title_box;
    if (key.startsWith("feature:")) return source.feature_slots.find((slot) => slot.id === key.slice(8))?.box ?? source.safe_area_box;
    return source[key as BoxKey];
  }, []);
  const withBox = useCallback((source: TemplateDefinition, key: RegionKey, box: Box): TemplateDefinition => {
    if (key.startsWith("text:")) return { ...source, text_slots: source.text_slots.map((slot) => slot.id === key.slice(5) ? { ...slot, box } : slot) };
    if (key.startsWith("feature:")) return { ...source, feature_slots: source.feature_slots.map((slot) => slot.id === key.slice(8) ? { ...slot, box } : slot) };
    return { ...source, [key]: box };
  }, []);
  const setBox = (key: RegionKey, box: Box) => setDraft((current) => withBox(current, key, box));
  const begin = (event: ReactPointerEvent, key: RegionKey, mode: "move" | ResizeHandle) => {
    event.preventDefault(); event.stopPropagation();
    setActiveKey(key);
    setInteraction({ key, mode, startX: event.clientX, startY: event.clientY, box: [...getBox(draft, key)] as Box, before: draft });
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const move = (event: ReactPointerEvent) => {
    if (!interaction || !canvasRef.current) return;
    const rect = canvasRef.current.getBoundingClientRect();
    let dx = (event.clientX - interaction.startX) / rect.width;
    let dy = (event.clientY - interaction.startY) / rect.height;
    if (interaction.mode === "move" && event.shiftKey) {
      if (Math.abs(dx) > Math.abs(dy)) dy = 0; else dx = 0;
    }
    const [x1, y1, x2, y2] = interaction.box;
    const allRegions: Array<{ key: RegionKey; box: Box }> = [
      { key: "safe_area_box", box: draft.safe_area_box }, { key: "product_box", box: draft.product_box },
      { key: "product_anchor_box", box: draft.product_anchor_box },
      ...draft.text_slots.map((slot) => ({ key: `text:${slot.id}` as RegionKey, box: slot.box })),
      ...draft.feature_slots.map((slot) => ({ key: `feature:${slot.id}` as RegionKey, box: slot.box })),
    ];
    const otherBoxes = allRegions.filter((row) => row.key !== interaction.key).map((row) => row.box);
    const targetsX = [.01, .5, .99, ...otherBoxes.flatMap((box) => [box[0], (box[0] + box[2]) / 2, box[2]])];
    const targetsY = [.01, .5, .99, ...otherBoxes.flatMap((box) => [box[1], (box[1] + box[3]) / 2, box[3]])];
    const thresholdX = event.altKey ? 0 : 6 / rect.width;
    const thresholdY = event.altKey ? 0 : 6 / rect.height;
    const minimumWidth = 0.06;
    const minimumHeight = 0.04;
    let next: Box;
    if (interaction.mode !== "move") {
      const handle = interaction.mode;
      let left = x1; let top = y1; let right = x2; let bottom = y2;
      if (handle.includes("w")) left = clamp(snapEdge(x1 + dx, targetsX, thresholdX), .01, x2 - minimumWidth);
      if (handle.includes("e")) right = clamp(snapEdge(x2 + dx, targetsX, thresholdX), x1 + minimumWidth, .99);
      if (handle.includes("n")) top = clamp(snapEdge(y1 + dy, targetsY, thresholdY), .01, y2 - minimumHeight);
      if (handle.includes("s")) bottom = clamp(snapEdge(y2 + dy, targetsY, thresholdY), y1 + minimumHeight, .99);
      next = [left, top, right, bottom];
    } else {
      const width = x2 - x1; const height = y2 - y1;
      const left = clamp(snapPosition(x1 + dx, width, targetsX, thresholdX), .01, .99 - width);
      const top = clamp(snapPosition(y1 + dy, height, targetsY, thresholdY), .01, .99 - height);
      next = [left, top, left + width, top + height];
    }
    setBox(interaction.key, next.map((part) => Math.round(part * 10000) / 10000) as Box);
  };
  const end = () => {
    if (interaction && JSON.stringify(getBox(interaction.before, interaction.key)) !== JSON.stringify(getBox(draft, interaction.key))) commit(draft);
    setInteraction(null);
  };

  const updateBoxField = (index: number, value: number) => {
    const current = [...getBox(draft, activeKey)] as Box;
    const normalized = index % 2 === 0 ? value / library.width : value / library.height;
    current[index] = clamp(normalized, .01, .99);
    if (current[2] - current[0] < .06 || current[3] - current[1] < .04) return;
    commit(withBox(draft, activeKey, current));
  };

  const updateGeometry = (field: "x" | "y" | "w" | "h", value: number) => {
    const [x1, y1, x2, y2] = getBox(draft, activeKey);
    const width = x2 - x1; const height = y2 - y1;
    let next: Box = [x1, y1, x2, y2];
    if (field === "x") { const left = clamp(value / library.width, .01, .99 - width); next = [left, y1, left + width, y2]; }
    if (field === "y") { const top = clamp(value / library.height, .01, .99 - height); next = [x1, top, x2, top + height]; }
    if (field === "w") next = [x1, y1, clamp(x1 + value / library.width, x1 + .06, .99), y2];
    if (field === "h") next = [x1, y1, x2, clamp(y1 + value / library.height, y1 + .04, .99)];
    commit(withBox(draft, activeKey, next));
  };

  const nudge = useCallback((dx: number, dy: number) => {
    const [x1, y1, x2, y2] = getBox(draft, activeKey);
    const nx = dx / library.width; const ny = dy / library.height;
    const width = x2 - x1; const height = y2 - y1;
    const left = clamp(x1 + nx, .01, .99 - width); const top = clamp(y1 + ny, .01, .99 - height);
    commit(withBox(draft, activeKey, [left, top, left + width, top + height] as Box));
  }, [activeKey, commit, draft, getBox, library.height, library.width, withBox]);

  useEffect(() => {
    const keydown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement;
      if (["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;
      if (event.code === "Space") { setSpacePressed(true); event.preventDefault(); }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") { event.preventDefault(); event.shiftKey ? redo() : undo(); return; }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "y") { event.preventDefault(); redo(); return; }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") { event.preventDefault(); void save(false); return; }
      if (event.key === "0") { setZoom(75); setPan({ x: 0, y: 0 }); }
      if (event.key === "1") setZoom(100);
      if (event.key === "+" || event.key === "=") setZoom((value) => Math.min(400, value + 25));
      if (event.key === "-") setZoom((value) => Math.max(10, value - 25));
      const amount = event.shiftKey ? 10 : 1;
      if (event.key === "ArrowLeft") { event.preventDefault(); nudge(-amount, 0); }
      if (event.key === "ArrowRight") { event.preventDefault(); nudge(amount, 0); }
      if (event.key === "ArrowUp") { event.preventDefault(); nudge(0, -amount); }
      if (event.key === "ArrowDown") { event.preventDefault(); nudge(0, amount); }
    };
    const keyup = (event: KeyboardEvent) => { if (event.code === "Space") setSpacePressed(false); };
    window.addEventListener("keydown", keydown); window.addEventListener("keyup", keyup);
    return () => { window.removeEventListener("keydown", keydown); window.removeEventListener("keyup", keyup); };
  }, [nudge, redo, undo]);

  const save = async (publish: boolean) => {
    setBusy(publish ? "publish" : "save"); setError("");
    try {
      const saved = await api.updateTemplateDraft(draft.id, {
        name: draft.name, page_types: draft.page_types,
        title_box: draft.title_box, body_box: draft.body_box, text_slots: draft.text_slots,
        feature_slots: draft.feature_slots,
        product_box: draft.product_box, product_anchor_box: draft.product_anchor_box,
        safe_area_box: draft.safe_area_box, scene_prompt_hint: draft.scene_prompt_hint,
      });
      const result = publish ? await api.publishTemplate(saved.id) : saved;
      setSavedAt(new Date());
      setSavedSnapshot(result);
      await onSaved(result, publish);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "模板保存失败");
    } finally { setBusy(""); }
  };

  const activeBox = getBox(draft, activeKey);
  const geometry = {
    x: Math.round(activeBox[0] * library.width), y: Math.round(activeBox[1] * library.height),
    w: Math.round((activeBox[2] - activeBox[0]) * library.width), h: Math.round((activeBox[3] - activeBox[1]) * library.height),
  };
  const contains = (outer: Box, inner: Box) => inner[0] >= outer[0] && inner[1] >= outer[1] && inner[2] <= outer[2] && inner[3] <= outer[3];
  const validationIssues = [
    ...draft.text_slots.map((slot) => !contains(draft.safe_area_box, slot.box) ? `${slot.name}超出安全区` : ""),
    ...draft.feature_slots.map((slot) => !contains(draft.safe_area_box, slot.box) ? `${slot.name}超出安全区` : ""),
    !contains(draft.product_box, draft.product_anchor_box) ? "商品核心区必须位于商品允许区内" : "",
  ].filter(Boolean);
  const startPan = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!spacePressed && event.button !== 1) return;
    event.preventDefault(); setIsPanning(true);
    panStart.current = { x: event.clientX, y: event.clientY, originX: pan.x, originY: pan.y };
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const movePan = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!isPanning) return;
    setPan({ x: panStart.current.originX + event.clientX - panStart.current.x, y: panStart.current.originY + event.clientY - panStart.current.y });
  };
  const requestClose = () => {
    if (dirty) { setConfirmClose(true); return; }
    onClose();
  };
  return <div className="template-editor-backdrop">
    <section className="template-editor-panel">
      <header className="editor-topbar"><div className="editor-breadcrumb"><button onClick={requestClose}><Icon name="back"/>返回</button><span>版式中心</span><i>/</i><span>{library.name}</span><i>/</i><strong>V{draft.version}</strong></div><label className="editor-name"><input value={draft.name} aria-label="模板名称" onChange={(event) => { setSavedAt(null); setDraft({ ...draft, name: event.target.value }); }}/><Icon name="edit" size={15}/></label><div className="editor-save-state"><span className="status-dot ready"/>{savedAt ? `已保存 ${savedAt.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}` : dirty ? "当前有未保存修改" : "草稿已同步"}</div><div className="editor-command-bar"><IconButton icon="undo" label="撤销 Ctrl+Z" disabled={historyIndex <= 0} onClick={undo}/><IconButton icon="redo" label="重做 Ctrl+Shift+Z" disabled={historyIndex >= history.length - 1} onClick={redo}/><button className="secondary"><Icon name="preview"/>预览</button>{validationIssues.length > 0 && <button className="validation-trigger"><Icon name="alert"/>查看 {validationIssues.length} 个问题</button>}<button className="secondary" disabled={!!busy || !dirty} onClick={() => void save(false)}>{busy === "save" ? "保存中…" : "保存草稿"}</button><button className="primary" disabled={!!busy || validationIssues.length > 0} onClick={() => void save(true)}>{busy === "publish" ? "发布中…" : "发布"}</button></div></header>
      <div className="template-editor-workspace">
        <aside className="editor-layers"><header><strong>图层 / 区域</strong><Icon name="layers"/></header>
          <button className="editor-add-text" onClick={() => { const id = `text-${crypto.randomUUID()}`; const slot = { id, role: "custom" as const, name: `文本框 ${draft.text_slots.length + 1}`, box: [.1, .1, .42, .2] as Box, required: false, max_lines: 4, default_style: {} }; commit({ ...draft, text_slots: [...draft.text_slots, slot] }); setActiveKey(`text:${id}`); }}><Icon name="plus"/><span>新增文字预留框</span></button>
          <button className="editor-add-text feature" disabled={draft.feature_slots.length >= 3} onClick={() => { const id = `feature-${crypto.randomUUID()}`; const slot: TemplateDefinition["feature_slots"][number] = { id, name: `图文卖点组 ${draft.feature_slots.length + 1}`, box: [.08, .56, .48, .88], layout: "row", columns: 3, min_items: 2, max_items: 3, icon_position: "top", icon_scale: .28, item_gap: .025, icon_text_gap: .012, card_style: {}, title_style: {}, description_style: {} }; commit({ ...draft, feature_slots: [...draft.feature_slots, slot] }); setActiveKey(`feature:${id}`); }}><Icon name="plus"/><span>新增图文卖点预留区</span></button>
          {draft.text_slots.map((slot) => { const key = `text:${slot.id}` as RegionKey; return <button key={key} className={activeKey === key ? "active" : ""} onClick={() => setActiveKey(key)}><Icon name="grip"/><span>{slot.name}</span><Icon name="eye"/><Icon name="unlock"/></button>; })}
          {draft.feature_slots.map((slot) => { const key = `feature:${slot.id}` as RegionKey; return <button key={key} className={activeKey === key ? "active" : ""} onClick={() => setActiveKey(key)}><Icon name="grip"/><span>{slot.name}</span><Icon name="eye"/><Icon name="unlock"/></button>; })}
          {(["safe_area_box", "product_box", "product_anchor_box"] as BoxKey[]).map((key) => <button key={key} className={activeKey === key ? "active" : ""} onClick={() => setActiveKey(key)}><Icon name="grip"/><span>{boxLabel(key)}</span><Icon name="eye"/><Icon name={key === "safe_area_box" ? "lock" : "unlock"}/></button>)}<p>拖动调整区域，方向键精调位置</p>
        </aside>
        <div ref={stageRef} className={`editor-stage ${spacePressed ? "pan-ready" : ""} ${isPanning ? "panning" : ""}`} onPointerDown={startPan} onPointerMove={movePan} onPointerUp={() => setIsPanning(false)} onPointerCancel={() => setIsPanning(false)}>
          <div className="editor-canvas-transform" style={{ transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom / 75})` }}>
          <div className="canvas-dimension width">{library.width}px</div><div className="canvas-dimension height">{library.height}px</div>
          <div className="editor-canvas" ref={canvasRef} style={{ aspectRatio: `${library.width} / ${library.height}` }} onPointerMove={move} onPointerUp={end} onPointerCancel={end}>
            <div className="editor-environment" />
            {interaction && <><i className="alignment-guide vertical"/><i className="alignment-guide horizontal"/></>}
            <EditableBox label="安全区" kind="safe" box={draft.safe_area_box} active={activeKey === "safe_area_box"} onMove={(event) => begin(event, "safe_area_box", "move")} onResize={(event, handle) => begin(event, "safe_area_box", handle)} />
            {draft.text_slots.map((slot) => { const key = `text:${slot.id}` as RegionKey; return <EditableBox key={slot.id} label={slot.name} kind={slot.role === "headline" ? "title" : "body"} box={slot.box} active={activeKey === key} onMove={(event) => begin(event, key, "move")} onResize={(event, handle) => begin(event, key, handle)}><span>{slot.role === "headline" ? "高端洗护新境界" : "让专业护理融入理想生活"}</span></EditableBox>; })}
            {draft.feature_slots.map((slot) => { const key = `feature:${slot.id}` as RegionKey; return <EditableBox key={slot.id} label={slot.name} kind="feature" box={slot.box} active={activeKey === key} onMove={(event) => begin(event, key, "move")} onResize={(event, handle) => begin(event, key, handle)}><span className="feature-slot-sample">{Array.from({ length: slot.max_items }, (_, index) => <i key={index}><b>◇</b><em>卖点 {index + 1}</em></i>)}</span></EditableBox>; })}
            <EditableBox label="商品允许区" kind="allowed" box={draft.product_box} active={activeKey === "product_box"} onMove={(event) => begin(event, "product_box", "move")} onResize={(event, handle) => begin(event, "product_box", handle)} />
            <EditableBox label="商品核心区" kind="product" box={draft.product_anchor_box} active={activeKey === "product_anchor_box"} onMove={(event) => begin(event, "product_anchor_box", "move")} onResize={(event, handle) => begin(event, "product_anchor_box", handle)}><img className="editor-product-asset" src={api.resolveUrl(EDITOR_PRODUCT_ASSET)} alt="版式预览商品" /></EditableBox>
          </div>
          </div>
          <div className="editor-zoom-controls"><IconButton icon="hand" label="按住空格拖动画布"/><IconButton icon="zoom-out" label="缩小" onClick={() => setZoom((value) => Math.max(10, value - 25))}/><label><input type="number" min="10" max="400" value={zoom} onChange={(event) => setZoom(clamp(Number(event.target.value), 10, 400))}/><span>%</span></label><IconButton icon="zoom-in" label="放大" onClick={() => setZoom((value) => Math.min(400, value + 25))}/><IconButton icon="fit" label="适合视口" onClick={() => { setZoom(75); setPan({ x: 0, y: 0 }); }}/></div>
        </div>
        <aside className="editor-inspector">
          <div className="inspector-tabs"><button className="active">样式</button><button>数据</button></div>
          <section><h4>位置与尺寸</h4>
            {activeKey.startsWith("text:") && (() => { const id = activeKey.slice(5); const slot = draft.text_slots.find((item) => item.id === id); return slot ? <div className="template-text-properties"><label>名称<input value={slot.name} onChange={(event) => setDraft({ ...draft, text_slots: draft.text_slots.map((item) => item.id === id ? { ...item, name: event.target.value } : item) })} onBlur={() => commit(draft)}/></label><label>角色<select value={slot.role} onChange={(event) => commit({ ...draft, text_slots: draft.text_slots.map((item) => item.id === id ? { ...item, role: event.target.value as typeof item.role } : item) })}><option value="headline">标题</option><option value="body">正文</option><option value="badge">标签</option><option value="caption">说明</option><option value="custom">自定义</option></select></label><button className="danger-link" disabled={draft.text_slots.length <= 1} onClick={() => { commit({ ...draft, text_slots: draft.text_slots.filter((item) => item.id !== id) }); setActiveKey(`text:${draft.text_slots.find((item) => item.id !== id)?.id ?? ""}`); }}>删除此预留框</button></div> : null; })()}
            {activeKey.startsWith("feature:") && (() => { const id = activeKey.slice(8); const slot = draft.feature_slots.find((item) => item.id === id); if (!slot) return null; const update = (changes: Partial<typeof slot>) => commit({ ...draft, feature_slots: draft.feature_slots.map((item) => item.id === id ? { ...item, ...changes } : item) }); return <div className="template-feature-properties"><label>名称<input value={slot.name} onChange={(event) => setDraft({ ...draft, feature_slots: draft.feature_slots.map((item) => item.id === id ? { ...item, name: event.target.value } : item) })} onBlur={() => commit(draft)}/></label><label>排布<select value={slot.layout} onChange={(event) => update({ layout: event.target.value as typeof slot.layout })}><option value="row">横向排列</option><option value="column">纵向排列</option><option value="grid">网格排列</option></select></label><label>图标位置<select value={slot.icon_position} onChange={(event) => update({ icon_position: event.target.value as typeof slot.icon_position })}><option value="top">图标在上</option><option value="left">图标在左</option></select></label><label>默认数量<span className="feature-count-inputs"><input type="number" min="1" max={slot.max_items} value={slot.min_items} onChange={(event) => update({ min_items: Number(event.target.value) })}/><i>至</i><input type="number" min={slot.min_items} max="6" value={slot.max_items} onChange={(event) => update({ max_items: Number(event.target.value), columns: Math.min(slot.columns, Number(event.target.value)) })}/></span></label><label>列数<input type="number" min="1" max={slot.max_items} value={slot.columns} onChange={(event) => update({ columns: Number(event.target.value) })}/></label><button className="danger-link" onClick={() => { commit({ ...draft, feature_slots: draft.feature_slots.filter((item) => item.id !== id) }); setActiveKey(`text:${draft.text_slots[0]?.id ?? ""}`); }}>删除图文卖点预留区</button></div>; })()}
            <div className="geometry-grid">{(["x", "y", "w", "h"] as const).map((field) => <label key={field}><span>{field.toUpperCase()}</span><input type="number" value={geometry[field]} onChange={(event) => updateGeometry(field, Number(event.target.value))}/><i>px</i></label>)}</div><div className="nudge-controls"><button aria-label="左移 1px" onClick={() => nudge(-1, 0)}>←</button><button aria-label="上移 1px" onClick={() => nudge(0, -1)}>↑</button><button aria-label="下移 1px" onClick={() => nudge(0, 1)}>↓</button><button aria-label="右移 1px" onClick={() => nudge(1, 0)}>→</button><span>Shift + 方向键移动 10px</span></div>
          </section>
          {validationIssues.length > 0 && <section className="editor-validation"><h4><Icon name="alert"/>布局问题</h4>{validationIssues.map((issue) => <p key={issue}>{issue}<small>请调整区域位置或尺寸后再发布。</small></p>)}</section>}
          <section><h4>适用页面</h4><fieldset>{PAGE_TYPES.map(([value, label]) => <label className="check" key={value}><input type="checkbox" checked={draft.page_types.includes(value)} onChange={(event) => commit({ ...draft, page_types: event.target.checked ? [...draft.page_types, value] : draft.page_types.filter((item) => item !== value) })} />{label}</label>)}</fieldset></section>
          <section><label>场景生成提示<textarea rows={6} value={draft.scene_prompt_hint} onChange={(event) => { setSavedAt(null); setDraft({ ...draft, scene_prompt_hint: event.target.value }); }} onBlur={() => commit(draft)} /></label></section>
          {error && <div className="notice error">{error}</div>}
        </aside>
      </div>
      {confirmClose && <div className="confirm-backdrop" role="presentation"><section className="confirm-dialog" role="alertdialog" aria-modal="true" aria-labelledby="leave-editor-title"><Icon name="alert" size={28}/><div><h3 id="leave-editor-title">离开版式编辑器？</h3><p>当前模板还有未保存修改。离开后，这些调整将不会保留。</p></div><div className="confirm-actions"><button className="secondary" autoFocus onClick={() => setConfirmClose(false)}>继续编辑</button><button className="danger-button" onClick={onClose}>放弃修改并离开</button></div></section></div>}
    </section>
  </div>;
}

function EditableBox({ label, kind, box, active, children, onMove, onResize }: { label: string; kind: string; box: Box; active: boolean; children?: ReactNode; onMove: (event: ReactPointerEvent) => void; onResize: (event: ReactPointerEvent, handle: ResizeHandle) => void }) {
  return <div className={`editable-region ${kind} ${active ? "active" : ""}`} style={regionStyle(box)} onPointerDown={onMove}>
    <em>{label}</em>{children}{active && (["nw", "n", "ne", "e", "se", "s", "sw", "w"] as ResizeHandle[]).map((handle) => <button key={handle} type="button" className={`resize-handle handle-${handle}`} aria-label={`从${handle}方向调整${label}大小`} onPointerDown={(event) => onResize(event, handle)} />)}
  </div>;
}

function boxLabel(key: BoxKey) {
  return ({ safe_area_box: "安全区", title_box: "标题框", body_box: "正文框", product_box: "商品允许区", product_anchor_box: "商品核心区" } as const)[key];
}
