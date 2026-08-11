import { FormEvent, PointerEvent as ReactPointerEvent, ReactNode, useEffect, useMemo, useRef, useState } from "react";

import { api, ImageCapabilities, LayoutLibrary, TemplateDefinition } from "./api";

type BoxKey = "safe_area_box" | "title_box" | "body_box" | "product_box" | "product_anchor_box";
type Box = [number, number, number, number];

const PAGE_TYPES = [
  ["hero", "主视觉"],
  ["selling_point", "核心卖点"],
  ["function", "功能说明"],
  ["scene", "生活场景"],
  ["parameters", "商品参数"],
] as const;

const regionStyle = (box: Box) => ({
  left: `${box[0] * 100}%`, top: `${box[1] * 100}%`,
  width: `${(box[2] - box[0]) * 100}%`, height: `${(box[3] - box[1]) * 100}%`,
});

const clamp = (value: number, minimum: number, maximum: number) => Math.min(maximum, Math.max(minimum, value));

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
    if (!window.confirm(`删除“${template.name}”V${template.version} 草稿？已发布版本不会受影响。`)) return;
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
            <div className="template-card-actions"><button className="secondary" disabled={busy === `version-${template.id}`} onClick={() => void editTemplate(template)}>{template.status === "published" ? "创建新版本并编辑" : "继续编辑"}</button>{template.status === "draft" && <button className="ghost-button danger" disabled={busy === `delete-${template.id}`} onClick={() => void deleteDraft(template)}>{busy === `delete-${template.id}` ? "删除中…" : "删除草稿"}</button>}</div>
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
  </section>;
}

function TemplateMiniature({ template }: { template: TemplateDefinition }) {
  return <div className="layout-miniature" style={{ aspectRatio: `${template.width} / ${template.height}` }}>
    <div className="mini-environment" />
    <div className="mini-box title" style={regionStyle(template.title_box)}><b>标题</b></div>
    <div className="mini-box body" style={regionStyle(template.body_box)}><span>正文内容</span></div>
    <div className="mini-box allowed" style={regionStyle(template.product_box)} />
    <div className="mini-product" style={regionStyle(template.product_anchor_box)}><i /><b /></div>
    <small>{template.size}</small>
  </div>;
}

type Interaction = { key: BoxKey; mode: "move" | "resize"; startX: number; startY: number; box: Box };

function TemplateEditor({ template, library, onClose, onSaved }: { template: TemplateDefinition; library: LayoutLibrary; onClose: () => void; onSaved: (next: TemplateDefinition, published: boolean) => Promise<void> }) {
  const [draft, setDraft] = useState(template);
  const [activeKey, setActiveKey] = useState<BoxKey>("title_box");
  const [interaction, setInteraction] = useState<Interaction | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const canvasRef = useRef<HTMLDivElement>(null);

  useEffect(() => setDraft(template), [template]);

  const setBox = (key: BoxKey, box: Box) => setDraft((current) => ({ ...current, [key]: box }));
  const begin = (event: ReactPointerEvent, key: BoxKey, mode: "move" | "resize") => {
    event.preventDefault(); event.stopPropagation();
    setActiveKey(key);
    setInteraction({ key, mode, startX: event.clientX, startY: event.clientY, box: [...draft[key]] as Box });
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const move = (event: ReactPointerEvent) => {
    if (!interaction || !canvasRef.current) return;
    const rect = canvasRef.current.getBoundingClientRect();
    const dx = (event.clientX - interaction.startX) / rect.width;
    const dy = (event.clientY - interaction.startY) / rect.height;
    const [x1, y1, x2, y2] = interaction.box;
    const minimumWidth = 0.06;
    const minimumHeight = 0.04;
    let next: Box;
    if (interaction.mode === "resize") {
      next = [x1, y1, clamp(x2 + dx, x1 + minimumWidth, .99), clamp(y2 + dy, y1 + minimumHeight, .99)];
    } else {
      const width = x2 - x1; const height = y2 - y1;
      const left = clamp(x1 + dx, .01, .99 - width); const top = clamp(y1 + dy, .01, .99 - height);
      next = [left, top, left + width, top + height];
    }
    setBox(interaction.key, next.map((part) => Math.round(part * 10000) / 10000) as Box);
  };
  const end = () => setInteraction(null);

  const save = async (publish: boolean) => {
    setBusy(publish ? "publish" : "save"); setError("");
    try {
      const saved = await api.updateTemplateDraft(draft.id, {
        name: draft.name, page_types: draft.page_types,
        title_box: draft.title_box, body_box: draft.body_box,
        product_box: draft.product_box, product_anchor_box: draft.product_anchor_box,
        safe_area_box: draft.safe_area_box, scene_prompt_hint: draft.scene_prompt_hint,
      });
      const result = publish ? await api.publishTemplate(saved.id) : saved;
      await onSaved(result, publish);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "模板保存失败");
    } finally { setBusy(""); }
  };

  const activeBox = draft[activeKey];
  return <div className="template-editor-backdrop">
    <section className="template-editor-panel">
      <header><div><p className="eyebrow">{library.name} · {library.size}</p><h3>模板编辑器</h3><p>画布按 {ratioLabel(library)} 比例缩放；坐标同时用于文字排版、Prompt 构图和质检。</p></div><button className="icon-button" onClick={onClose}>×</button></header>
      <div className="template-editor-workspace">
        <div className="editor-stage">
          <div className="editor-canvas" ref={canvasRef} style={{ aspectRatio: `${library.width} / ${library.height}` }} onPointerMove={move} onPointerUp={end} onPointerCancel={end}>
            <div className="editor-environment" />
            <EditableBox label="安全区" kind="safe" box={draft.safe_area_box} active={activeKey === "safe_area_box"} onMove={(event) => begin(event, "safe_area_box", "move")} onResize={(event) => begin(event, "safe_area_box", "resize")} />
            <EditableBox label="标题" kind="title" box={draft.title_box} active={activeKey === "title_box"} onMove={(event) => begin(event, "title_box", "move")} onResize={(event) => begin(event, "title_box", "resize")}><strong>高端洗护新境界</strong></EditableBox>
            <EditableBox label="正文" kind="body" box={draft.body_box} active={activeKey === "body_box"} onMove={(event) => begin(event, "body_box", "move")} onResize={(event) => begin(event, "body_box", "resize")}><span>让专业护理自然融入理想生活</span></EditableBox>
            <EditableBox label="商品允许区" kind="allowed" box={draft.product_box} active={activeKey === "product_box"} onMove={(event) => begin(event, "product_box", "move")} onResize={(event) => begin(event, "product_box", "resize")} />
            <EditableBox label="商品核心区" kind="product" box={draft.product_anchor_box} active={activeKey === "product_anchor_box"} onMove={(event) => begin(event, "product_anchor_box", "move")} onResize={(event) => begin(event, "product_anchor_box", "resize")}><span className="editor-product-shape"><i /><b /></span></EditableBox>
          </div>
          <p className="editor-scale-note">预览按容器缩放，实际输出 {library.width} × {library.height}px</p>
        </div>
        <aside className="editor-inspector">
          <label>模板名称<input value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} /></label>
          <fieldset><legend>适用页面</legend>{PAGE_TYPES.map(([value, label]) => <label className="check" key={value}><input type="checkbox" checked={draft.page_types.includes(value)} onChange={(event) => setDraft({ ...draft, page_types: event.target.checked ? [...draft.page_types, value] : draft.page_types.filter((item) => item !== value) })} />{label}</label>)}</fieldset>
          <label>场景生成提示<textarea rows={5} value={draft.scene_prompt_hint} onChange={(event) => setDraft({ ...draft, scene_prompt_hint: event.target.value })} /></label>
          <div className="coordinate-panel"><strong>{boxLabel(activeKey)}</strong><span>百分比坐标</span><code>{activeBox.map((value) => `${Math.round(value * 1000) / 10}%`).join(" · ")}</code><span>实际像素</span><code>{Math.round(activeBox[0] * library.width)}, {Math.round(activeBox[1] * library.height)}, {Math.round(activeBox[2] * library.width)}, {Math.round(activeBox[3] * library.height)}</code></div>
          <div className="editor-legend"><span className="title">标题框</span><span className="body">正文框</span><span className="product">商品核心区</span><span className="allowed">商品允许区</span></div>
          {error && <div className="notice error">{error}</div>}
        </aside>
      </div>
      <footer><button className="secondary" onClick={onClose}>取消</button><button className="secondary" disabled={!!busy} onClick={() => void save(false)}>{busy === "save" ? "保存中…" : "保存草稿"}</button><button className="primary" disabled={!!busy} onClick={() => void save(true)}>{busy === "publish" ? "发布中…" : `发布 V${draft.version}`}</button></footer>
    </section>
  </div>;
}

function EditableBox({ label, kind, box, active, children, onMove, onResize }: { label: string; kind: string; box: Box; active: boolean; children?: ReactNode; onMove: (event: ReactPointerEvent) => void; onResize: (event: ReactPointerEvent) => void }) {
  return <div className={`editable-region ${kind} ${active ? "active" : ""}`} style={regionStyle(box)} onPointerDown={onMove}>
    <em>{label}</em>{children}<button type="button" aria-label={`调整${label}大小`} onPointerDown={onResize} />
  </div>;
}

function boxLabel(key: BoxKey) {
  return ({ safe_area_box: "安全区", title_box: "标题框", body_box: "正文框", product_box: "商品允许区", product_anchor_box: "商品核心区" } as const)[key];
}
