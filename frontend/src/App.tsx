import { FormEvent, ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import {
  api,
  Asset,
  Batch,
  PageItem,
  PagePlan,
  ProductionSnapshot,
  PromptVersion,
  ProductProfile,
  Project,
  Recipe,
  TemplateDefinition,
} from "./api";

type Tab = "projects" | "batches" | "catalog";
type Role = "business" | "admin";

const emptyProfile = (): ProductProfile => ({
  sku: "",
  name: "",
  category: "洗衣机",
  model: "",
  selling_points: [],
  parameters: {},
  reference_assets: [],
  brand_requirements: "",
  output_requirements: "",
});

function App() {
  const [tab, setTab] = useState<Tab>("projects");
  const [projects, setProjects] = useState<Project[]>([]);
  const [batches, setBatches] = useState<Batch[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showProjectForm, setShowProjectForm] = useState(false);
  const [showBatchForm, setShowBatchForm] = useState(false);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [role, setRole] = useState<Role>("admin");

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [projectRows, batchRows] = await Promise.all([api.listProjects(), api.listBatches()]);
      setProjects(projectRows);
      setBatches(batchRows);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => void refresh(), [refresh]);

  const activeCount = useMemo(
    () => projects.filter((project) => !["completed", "archived"].includes(project.status)).length,
    [projects],
  );
  const batchSkuCount = useMemo(
    () => batches.reduce((total, batch) => total + (batch.progress.total ?? batch.items.length), 0),
    [batches],
  );

  return (
    <div className="app-shell">
      <Sidebar tab={tab} role={role} setRole={(next) => { setRole(next); if (next === "business" && tab === "catalog") setTab("projects"); setSelectedProjectId(null); }} setTab={(next) => { setTab(next); setSelectedProjectId(null); }} />
      {selectedProjectId ? (
        <ProjectWorkspace
          projectId={selectedProjectId}
          onBack={() => setSelectedProjectId(null)}
          onChanged={refresh}
        />
      ) : (
        <main>
          <header className="topbar">
            <div><p className="eyebrow">WORKSPACE</p><h2>{tabTitle(tab)}</h2></div>
            {tab !== "catalog" && (
              <button className="primary" onClick={() => tab === "projects" ? setShowProjectForm(true) : setShowBatchForm(true)}>
                ＋ {tab === "projects" ? "新建项目" : "新建批次"}
              </button>
            )}
          </header>

          <section className="metrics">
            <Metric label="项目总数" value={projects.length} hint="本地持久化" />
            <Metric label="进行中" value={activeCount} hint="待策划或生产" />
            <Metric label="批量任务" value={batches.length} hint={`${batchSkuCount} 个 SKU`} />
            <Metric label="当前阶段" value="策划与模板" hint="素材、导入、规划" text />
          </section>

          {error && <div className="notice error">{error}</div>}
          {loading ? <div className="empty-state">正在连接本地服务…</div> : (
            tab === "projects" ? <ProjectTable projects={projects} onOpen={setSelectedProjectId} onRefresh={refresh} /> :
            tab === "batches" ? <BatchTable batches={batches} onOpenProject={setSelectedProjectId} onRefresh={refresh} /> :
            <CatalogPanel />
          )}
        </main>
      )}

      {showProjectForm && <ProjectForm onClose={() => setShowProjectForm(false)} onCreated={async () => { setShowProjectForm(false); await refresh(); }} />}
      {showBatchForm && <BatchForm onClose={() => setShowBatchForm(false)} onCreated={async () => { setShowBatchForm(false); await refresh(); }} />}
    </div>
  );
}

function Sidebar({ tab, role, setRole, setTab }: { tab: Tab; role: Role; setRole: (role: Role) => void; setTab: (tab: Tab) => void }) {
  return <aside className="sidebar">
    <div className="brand-mark">PC</div>
    <div><p className="eyebrow">PRODUCT CONTENT</p><h1>商品内容生产平台</h1></div>
    <nav>
      <button className={tab === "projects" ? "active" : ""} onClick={() => setTab("projects")}><span>01</span> 商品项目</button>
      <button className={tab === "batches" ? "active" : ""} onClick={() => setTab("batches")}><span>02</span> 批量任务</button>
      {role === "admin" && <button className={tab === "catalog" ? "active" : ""} onClick={() => setTab("catalog")}><span>03</span> 固定配置</button>}
    </nav>
    <div className="role-switch"><span>当前角色</span><select value={role} onChange={(event) => setRole(event.target.value as Role)}><option value="business">业务用户</option><option value="admin">管理员 / 专家</option></select></div>
    <div className="sidebar-foot"><span className="status-dot" /> 本地开发环境</div>
  </aside>;
}

function ProjectWorkspace({ projectId, onBack, onChanged }: { projectId: string; onBack: () => void; onChanged: () => Promise<void> }) {
  const [project, setProject] = useState<Project | null>(null);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [plan, setPlan] = useState<PagePlan | null>(null);
  const [templates, setTemplates] = useState<TemplateDefinition[]>([]);
  const [recipes, setRecipes] = useState<Recipe[]>([]);
  const [production, setProduction] = useState<ProductionSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [editingProfile, setEditingProfile] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [projectRow, assetRows, planRow, templateRows, recipeRows] = await Promise.all([
        api.getProject(projectId), api.listAssets(projectId), api.getPlan(projectId), api.listTemplates(), api.listRecipes(),
      ]);
      setProject(projectRow); setAssets(assetRows); setPlan(planRow); setTemplates(templateRows); setRecipes(recipeRows);
      if (planRow) {
        setProduction(await api.getProduction(projectId));
      } else {
        setProduction(null);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "项目加载失败");
    } finally { setLoading(false); }
  }, [projectId]);

  useEffect(() => void load(), [load]);

  useEffect(() => {
    if (!production?.pages.some((row) => row.job && ["queued", "running"].includes(row.job.status))) return;
    const timer = window.setTimeout(() => void api.getProduction(projectId).then(setProduction), 900);
    return () => window.clearTimeout(timer);
  }, [production, projectId]);

  async function generatePlan() {
    setBusy("generate"); setError(""); setMessage("");
    try { setPlan(await api.generatePlan(projectId)); setProduction(null); setMessage("已根据商品档案生成 5 页内容规划"); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "生成失败"); }
    finally { setBusy(""); }
  }

  async function savePlan(confirmed: boolean) {
    if (!plan) return;
    setBusy(confirmed ? "confirm" : "save"); setError(""); setMessage("");
    try {
      const saved = await api.savePlan(projectId, { items: plan.items, confirmed });
      setPlan(saved);
      setProduction(await api.getProduction(projectId));
      setMessage(confirmed ? "页面规划已确认，可以进入生产阶段" : "页面规划草稿已保存");
      if (confirmed) { await onChanged(); setProject(await api.getProject(projectId)); }
    } catch (reason) { setError(reason instanceof Error ? reason.message : "保存失败"); }
    finally { setBusy(""); }
  }

  function updatePage(index: number, patch: Partial<PageItem>) {
    if (!plan) return;
    setPlan({ ...plan, confirmed: false, items: plan.items.map((item, itemIndex) => itemIndex === index ? { ...item, ...patch, status: "draft" } : item) });
  }

  function movePage(index: number, direction: -1 | 1) {
    if (!plan) return;
    const target = index + direction;
    if (target < 0 || target >= plan.items.length) return;
    const items = [...plan.items];
    [items[index], items[target]] = [items[target], items[index]];
    setPlan({ ...plan, confirmed: false, items: items.map((item, itemIndex) => ({ ...item, order: itemIndex + 1, status: "draft" })) });
  }

  function deletePage(index: number) {
    if (!plan || plan.items.length <= 1) return;
    setPlan({ ...plan, confirmed: false, items: plan.items.filter((_, itemIndex) => itemIndex !== index).map((item, itemIndex) => ({ ...item, order: itemIndex + 1, status: "draft" })) });
  }

  function addPage() {
    if (!plan) return;
    const template = templates.find((item) => item.page_types.includes("selling_point")) ?? templates[0];
    setPlan({ ...plan, confirmed: false, items: [...plan.items, { id: crypto.randomUUID(), order: plan.items.length + 1, page_type: "selling_point", title: "新页面标题", body: "请填写页面文案", visual_goal: "请填写视觉目标", template_id: template?.id ?? "split-left", heading_level: 2, status: "draft" }] });
  }

  if (loading || !project) return <main><div className="empty-state">正在加载项目工作台…</div></main>;
  return <main className="project-workspace">
    <header className="topbar workspace-topbar">
      <div><button className="back-button" onClick={onBack}>← 返回项目</button><p className="eyebrow">{project.profile.sku} · {project.profile.category}</p><h2>{project.name}</h2></div>
      <StatusBadge status={project.status} />
    </header>
    <div className="workflow-strip">
      <span className="done">1 商品资料</span><i>→</i><span className={plan ? "done" : "active"}>2 内容规划</span><i>→</i><span className={plan?.confirmed ? "done" : ""}>3 固定配方</span><i>→</i><span className={production?.pages.some((row) => row.candidates.length) ? "done" : ""}>4 图片生产与质检</span>
    </div>
    {error && <div className="notice error">{error}</div>}
    {message && <div className="notice success">{message}</div>}

    <section className="workspace-grid">
      <article className="panel compact-panel">
        <div className="panel-heading editable-heading"><div><h3>商品档案</h3><p>数字、型号和参数作为已确认事实进入后续生成。</p></div><button className="ghost-button mini" onClick={() => setEditingProfile(true)}>编辑资料</button></div>
        <div className="profile-details">
          <Info label="商品名称" value={project.profile.name} /><Info label="SKU / 型号" value={`${project.profile.sku} / ${project.profile.model || "—"}`} />
          <Info label="品类" value={project.profile.category} /><Info label="核心卖点" value={project.profile.selling_points.join("、") || "暂未填写"} wide />
          <Info label="商品参数" value={Object.entries(project.profile.parameters).map(([key, value]) => `${key} ${value}`).join(" · ") || "暂未填写"} wide />
        </div>
      </article>
      <AssetPanel projectId={projectId} assets={assets} onUploaded={async () => { setAssets(await api.listAssets(projectId)); setProject(await api.getProject(projectId)); }} />
    </section>

    <section className="panel planning-panel">
      <div className="panel-heading planning-heading">
        <div><h3>多页内容规划</h3><p>{plan ? `版本 V${plan.version} · ${plan.confirmed ? "已确认" : "草稿"}` : "基于商品资料生成主视觉、卖点、功能、场景和参数页。"}</p></div>
        <div className="button-row">
          {plan && <button className="ghost-button" disabled={!!busy} onClick={addPage}>＋ 新增页面</button>}
          {plan && <><button className="secondary" disabled={!!busy} onClick={() => void savePlan(false)}>{busy === "save" ? "保存中…" : "保存草稿"}</button><button className="primary" disabled={!!busy} onClick={() => void savePlan(true)}>{busy === "confirm" ? "确认中…" : "确认规划"}</button></>}
          <button className={plan ? "ghost-button" : "primary"} disabled={!!busy} onClick={() => void generatePlan()}>{busy === "generate" ? "生成中…" : plan ? "重新生成" : "生成内容规划"}</button>
        </div>
      </div>
      {!plan ? <div className="empty-state inline-empty">录入卖点和参数后，可生成一套五页内容结构。</div> : <div className="plan-list">
        <div className="recipe-banner"><div><span>可用配方</span><strong>{recipes.filter((item) => item.status === "published").length} 套已发布配方</strong></div><small>在生产阶段选择配方，生成记录会锁定具体版本</small></div>
        {plan.items.map((item, index) => <PageEditor key={item.id} item={item} templates={templates} onChange={(patch) => updatePage(index, patch)} onMoveUp={() => movePage(index, -1)} onMoveDown={() => movePage(index, 1)} onDelete={() => deletePage(index)} first={index === 0} last={index === plan.items.length - 1} />)}
      </div>}
    </section>
    {plan?.confirmed && <ProductionPanel projectId={projectId} recipes={recipes} referenceUrl={(() => { const reference = assets.find((item) => item.usage === "product" && item.mime_type.startsWith("image/")); return reference ? api.assetUrl(reference.id) : ""; })()} snapshot={production} onRefresh={async () => { setProduction(await api.getProduction(projectId)); setProject(await api.getProject(projectId)); await onChanged(); }} />}
    {editingProfile && <ProfileEditor project={project} onClose={() => setEditingProfile(false)} onSaved={async () => { setEditingProfile(false); await load(); await onChanged(); setMessage("商品档案已更新，再次确认页面规划后可重新生产"); }} />}
  </main>;
}

function AssetPanel({ projectId, assets, onUploaded }: { projectId: string; assets: Asset[]; onUploaded: () => Promise<void> }) {
  const [file, setFile] = useState<File | null>(null);
  const [usage, setUsage] = useState<Asset["usage"]>("product");
  const [authorizationStatus, setAuthorizationStatus] = useState<Asset["authorization_status"]>("unconfirmed");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function upload(event: FormEvent) {
    event.preventDefault(); if (!file) return;
    setBusy(true); setError("");
    try { await api.uploadAsset(projectId, file, usage, authorizationStatus); setFile(null); await onUploaded(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "上传失败"); }
    finally { setBusy(false); }
  }
  return <article className="panel compact-panel">
    <div className="panel-heading"><h3>参考素材</h3><p>支持商品、细节、品牌和场景参考，单文件不超过 25MB。</p></div>
    <form className="asset-upload" onSubmit={upload}>
      <select value={usage} onChange={(event) => setUsage(event.target.value as Asset["usage"])}><option value="product">商品外观</option><option value="detail">局部细节</option><option value="brand">品牌风格</option><option value="scene">场景参考</option></select>
      <select value={authorizationStatus} onChange={(event) => setAuthorizationStatus(event.target.value as Asset["authorization_status"])}><option value="unconfirmed">授权待确认</option><option value="authorized">已授权使用</option><option value="restricted">限制使用</option></select>
      <label className="file-picker"><input type="file" accept=".png,.jpg,.jpeg,.webp,.pdf" onChange={(event) => setFile(event.target.files?.[0] ?? null)} /><span>{file?.name ?? "选择素材文件"}</span></label>
      <button className="secondary" disabled={!file || busy}>{busy ? "上传中…" : "上传"}</button>
    </form>
    {error && <div className="notice error">{error}</div>}
    <div className="asset-list">{assets.length === 0 ? <p className="muted">尚未上传参考素材</p> : assets.map((asset) => <a key={asset.id} href={api.assetUrl(asset.id)} target="_blank" rel="noreferrer" className="asset-item">{asset.mime_type.startsWith("image/") ? <img src={api.assetUrl(asset.id)} alt="" /> : <span className="pdf-icon">PDF</span>}<div><strong>{asset.file_name}</strong><small>{usageLabel(asset.usage)} · {formatBytes(asset.size_bytes)} · {asset.authorization_status === "authorized" ? "已授权" : asset.authorization_status === "restricted" ? "限制使用" : "授权待确认"}</small></div></a>)}</div>
  </article>;
}

function ProfileEditor({ project, onClose, onSaved }: { project: Project; onClose: () => void; onSaved: () => Promise<void> }) {
  const [projectName, setProjectName] = useState(project.name);
  const [profile, setProfile] = useState(project.profile);
  const [sellingPoints, setSellingPoints] = useState(project.profile.selling_points.join("\n"));
  const [parameters, setParameters] = useState(Object.entries(project.profile.parameters).map(([key, value]) => `${key}=${value}`).join("\n"));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault(); setSaving(true); setError("");
    try {
      const parsedParameters = Object.fromEntries(parameters.split(/\n|[;；]/).map((row) => row.trim()).filter(Boolean).map((row) => row.split(/[=：:]/, 2).map((part) => part.trim())).filter(([key, value]) => key && value));
      await api.updateProject(project.id, { project_name: projectName, profile: { ...profile, selling_points: sellingPoints.split("\n").map((item) => item.trim()).filter(Boolean), parameters: parsedParameters } });
      await onSaved();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "更新失败"); }
    finally { setSaving(false); }
  }
  return <Dialog title="编辑商品档案" subtitle="型号、数字和参数将作为质检的事实依据。" onClose={onClose}><form onSubmit={submit}><Field label="项目名称"><input required value={projectName} onChange={(event) => setProjectName(event.target.value)} /></Field><div className="form-grid"><Field label="SKU"><input required value={profile.sku} onChange={(event) => setProfile({ ...profile, sku: event.target.value })} /></Field><Field label="型号"><input value={profile.model} onChange={(event) => setProfile({ ...profile, model: event.target.value })} /></Field><Field label="商品名称"><input required value={profile.name} onChange={(event) => setProfile({ ...profile, name: event.target.value })} /></Field><Field label="品类"><input required value={profile.category} onChange={(event) => setProfile({ ...profile, category: event.target.value })} /></Field></div><Field label="核心卖点（每行一项）"><textarea rows={3} value={sellingPoints} onChange={(event) => setSellingPoints(event.target.value)} /></Field><Field label="商品参数（每行：名称=值）"><textarea rows={3} value={parameters} onChange={(event) => setParameters(event.target.value)} /></Field><Field label="品牌要求"><textarea rows={2} value={profile.brand_requirements} onChange={(event) => setProfile({ ...profile, brand_requirements: event.target.value })} /></Field><Field label="输出要求"><textarea rows={2} value={profile.output_requirements} onChange={(event) => setProfile({ ...profile, output_requirements: event.target.value })} /></Field>{error && <div className="notice error">{error}</div>}<FormActions onClose={onClose} saving={saving} label="保存档案" /></form></Dialog>;
}

function PageEditor({ item, templates, onChange, onMoveUp, onMoveDown, onDelete, first, last }: { item: PageItem; templates: TemplateDefinition[]; onChange: (patch: Partial<PageItem>) => void; onMoveUp: () => void; onMoveDown: () => void; onDelete: () => void; first: boolean; last: boolean }) {
  const template = templates.find((row) => row.id === item.template_id) ?? templates[0];
  const compatible = templates.filter((row) => row.page_types.includes(item.page_type));
  return <article className="page-editor">
    <TemplatePreview item={item} template={template} />
    <div className="page-fields">
      <div className="page-meta"><span>第 {item.order} 页 · {pageTypeLabel(item.page_type)}</span><div className="page-tools"><select aria-label="标题层级" value={item.heading_level} onChange={(event) => onChange({ heading_level: Number(event.target.value) as PageItem["heading_level"] })}><option value="1">H1</option><option value="2">H2</option><option value="3">H3</option><option value="4">H4</option><option value="5">H5</option></select><select value={item.page_type} onChange={(event) => { const pageType = event.target.value as PageItem["page_type"]; const nextTemplate = templates.find((row) => row.page_types.includes(pageType)); onChange({ page_type: pageType, template_id: nextTemplate?.id ?? item.template_id }); }}><option value="hero">主视觉</option><option value="selling_point">核心卖点</option><option value="function">功能说明</option><option value="scene">场景</option><option value="parameters">参数</option></select><select value={item.template_id} onChange={(event) => onChange({ template_id: event.target.value })}>{compatible.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}</select><button title="上移" disabled={first} onClick={onMoveUp}>↑</button><button title="下移" disabled={last} onClick={onMoveDown}>↓</button><button title="删除" disabled={first && last} onClick={onDelete}>×</button></div></div>
      <Field label="页面标题"><input value={item.title} onChange={(event) => onChange({ title: event.target.value })} /></Field>
      <Field label="正文文案"><textarea rows={2} value={item.body} onChange={(event) => onChange({ body: event.target.value })} /></Field>
      <Field label="视觉目标"><textarea rows={2} value={item.visual_goal} onChange={(event) => onChange({ visual_goal: event.target.value })} /></Field>
    </div>
  </article>;
}

function TemplatePreview({ item, template }: { item: PageItem; template?: TemplateDefinition }) {
  return <div className={`template-preview ${template?.layout ?? "center"}`}><div className="safe-area"><div className="preview-copy"><strong>{item.title}</strong><span>{item.body}</span></div><div className="product-shape"><i /><b /></div></div><small>{template?.name ?? item.template_id}</small></div>;
}

function ProductionPanel({ projectId, recipes, referenceUrl, snapshot, onRefresh }: { projectId: string; recipes: Recipe[]; referenceUrl: string; snapshot: ProductionSnapshot | null; onRefresh: () => Promise<void> }) {
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [downloadUrl, setDownloadUrl] = useState("");
  const publishedRecipes = recipes.filter((item) => item.status === "published");
  const [recipeId, setRecipeId] = useState(publishedRecipes[0]?.id ?? "commerce-detail-v1");
  const [message, setMessage] = useState("");
  const hasResults = snapshot?.pages.some((row) => row.candidates.length > 0) ?? false;
  async function start(force: boolean) {
    setBusy(force ? "regenerate" : "start"); setError(""); setMessage(""); setDownloadUrl("");
    try { await api.startProduction(projectId, force, recipeId); await onRefresh(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "生产任务启动失败"); }
    finally { setBusy(""); }
  }
  async function exportResult() {
    setBusy("export"); setError("");
    try { const result = await api.exportProject(projectId); setDownloadUrl(api.resolveUrl(result.download_url)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "导出失败"); }
    finally { setBusy(""); }
  }
  async function recompose(pageId: string) { setBusy(`recompose-${pageId}`); setError(""); try { await api.recomposePage(projectId, pageId); await onRefresh(); } catch (reason) { setError(reason instanceof Error ? reason.message : "重新排版失败"); } finally { setBusy(""); } }
  async function regenerate(pageId: string) { setBusy(`regenerate-${pageId}`); setError(""); setMessage(""); try { await api.regeneratePage(projectId, pageId, recipeId); await onRefresh(); } catch (reason) { setError(reason instanceof Error ? reason.message : "单页重生成失败"); } finally { setBusy(""); } }
  async function saveAsRecipe() { setBusy("recipe"); setError(""); try { const recipe = await api.createRecipeCandidate(projectId, `${snapshot?.project.profile.sku ?? "商品"}验证配方`); setMessage(`已生成配方草稿：${recipe.name}，请到固定配置中测试并发布。`); } catch (reason) { setError(reason instanceof Error ? reason.message : "配方沉淀失败"); } finally { setBusy(""); } }
  return <section className="panel production-panel">
    <div className="panel-heading planning-heading"><div><h3>图片生产、质检与审核</h3><p>底图与文字层分别保存；每页候选经过规则检查、评分和人工确认。</p></div><div className="production-controls"><select aria-label="生成配方" value={recipeId} onChange={(event) => setRecipeId(event.target.value)}>{publishedRecipes.map((recipe) => <option key={recipe.id} value={recipe.id}>{recipe.name} V{recipe.version}</option>)}</select><div className="button-row">{snapshot?.ready_for_export && <button className="ghost-button" disabled={!!busy} onClick={() => void saveAsRecipe()}>{busy === "recipe" ? "保存中…" : "沉淀为配方"}</button>}{hasResults && <button className="secondary" disabled={!!busy} onClick={() => void start(true)}>{busy === "regenerate" ? "重新生产中…" : "整套重新生产"}</button>}<button className="primary" disabled={!!busy || (hasResults && !snapshot?.ready_for_export)} onClick={() => hasResults ? void exportResult() : void start(false)}>{busy === "start" ? "正在生产…" : busy === "export" ? "正在打包…" : hasResults ? "导出正式结果" : "开始生产"}</button></div></div></div>
    {error && <div className="notice error">{error}</div>}
    {message && <div className="notice success">{message}</div>}
    {downloadUrl && <div className="notice success">正式结果已生成：<a href={downloadUrl}>下载 ZIP 交付包</a></div>}
    {!snapshot || !hasResults ? <div className="empty-state inline-empty">确认规划后，启动本地异步生产任务。</div> : <div className="production-pages">{snapshot.pages.map((row) => <article className="production-page" key={row.page.id}><div className="production-page-head"><div><span>第 {row.page.order} 页 · {pageTypeLabel(row.page.page_type)}</span><h4>{row.page.title}</h4></div><div>{row.candidates.length > 0 && <><button className="ghost-button mini" disabled={!!busy} onClick={() => void recompose(row.page.id)}>{busy === `recompose-${row.page.id}` ? "排版中…" : "仅重新排版"}</button><button className="ghost-button mini" disabled={!!busy} onClick={() => void regenerate(row.page.id)}>{busy === `regenerate-${row.page.id}` ? "重生成中…" : "重新生成本页"}</button></>}{row.job && <StatusBadge status={row.job.status} />}{row.decision?.decision === "approved" && <StatusBadge status="approved" />}</div></div>{row.job?.error && <div className="notice error">{row.job.error}</div>}<div className="candidate-grid">{row.candidates.map((candidate) => <CandidateCard key={candidate.id} candidate={candidate} referenceUrl={referenceUrl} selected={row.decision?.candidate_id === candidate.id && row.decision.decision === "approved"} onReviewed={onRefresh} />)}</div></article>)}</div>}
  </section>;
}

function CandidateCard({ candidate, referenceUrl, selected, onReviewed }: { candidate: ProductionSnapshot["pages"][number]["candidates"][number]; referenceUrl: string; selected: boolean; onReviewed: () => Promise<void> }) {
  const [reason, setReason] = useState(""); const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  const blocking = candidate.qa?.issues.some((issue) => ["P0", "P1"].includes(issue.severity));
  const layout = candidate.qa?.evidence?.layout as { canvas?: number[]; safe_area?: number[]; text_bbox?: number[]; subject_bbox?: number[] } | undefined;
  const overlay = (bbox?: number[]) => { const canvas = layout?.canvas ?? [900, 1200]; return bbox?.length === 4 ? { left: `${bbox[0] / canvas[0] * 100}%`, top: `${bbox[1] / canvas[1] * 100}%`, width: `${(bbox[2] - bbox[0]) / canvas[0] * 100}%`, height: `${(bbox[3] - bbox[1]) / canvas[1] * 100}%` } : undefined; };
  async function review(decision: "approved" | "rejected") { setBusy(true); setError(""); try { await api.reviewCandidate(candidate.id, decision, reason); await onReviewed(); } catch (value) { setError(value instanceof Error ? value.message : "审核失败"); } finally { setBusy(false); } }
  return <div className={`candidate-card ${selected ? "selected" : ""}`}><div className="candidate-image"><img src={api.resolveUrl(candidate.composed_url)} alt={`候选 ${candidate.candidate_index}`} />{layout?.safe_area && <i className="qa-box safe" style={overlay(layout.safe_area)} />}{layout?.subject_bbox && <i className="qa-box subject" style={overlay(layout.subject_bbox)} />}{layout?.text_bbox && <i className="qa-box text" style={overlay(layout.text_bbox)} />}<span>排名 #{candidate.rank}</span>{referenceUrl && <div className="reference-thumb"><img src={referenceUrl} alt="商品参考图" /><small>参考图</small></div>}</div><div className="candidate-summary"><div><strong>{candidate.score} 分</strong><StatusBadge status={candidate.qa?.status ?? "review"} /></div><p>{candidate.qa?.issues.length ? candidate.qa.issues.map((issue) => `${issue.severity} ${issue.message}`).join("；") : "未发现阻塞问题"}</p>{candidate.qa?.repair_applied && <small>已执行自动排版或一轮图片修复</small>}<details><summary>查看分层文件与质检证据</summary><div className="layer-links"><a href={api.resolveUrl(candidate.base_url)} target="_blank" rel="noreferrer">底图</a><a href={api.resolveUrl(candidate.text_layer_url)} target="_blank" rel="noreferrer">文字层</a><a href={api.resolveUrl(candidate.composed_url)} target="_blank" rel="noreferrer">合成图</a></div><pre>{JSON.stringify(candidate.qa?.evidence, null, 2)}</pre></details>{blocking && <input className="override-input" value={reason} onChange={(event) => setReason(event.target.value)} placeholder="P0/P1 人工覆盖原因（必填）" />}{error && <div className="notice error">{error}</div>}<div className="candidate-actions"><button className="secondary" disabled={busy} onClick={() => void review("rejected")}>不采用</button><button className="primary" disabled={busy || selected} onClick={() => void review("approved")}>{selected ? "已确认" : "确认此图"}</button></div></div></div>;
}

function ProjectTable({ projects, onOpen, onRefresh }: { projects: Project[]; onOpen: (id: string) => void; onRefresh: () => Promise<void> }) {
  const [busy, setBusy] = useState(""); const [error, setError] = useState("");
  async function clone(project: Project) { setBusy(project.id); setError(""); try { const copied = await api.cloneProject(project.id); await onRefresh(); onOpen(copied.id); } catch (reason) { setError(reason instanceof Error ? reason.message : "复制失败"); } finally { setBusy(""); } }
  return <section className="panel"><div className="panel-heading"><h3>最近项目</h3><p>进入项目后上传素材、生成并确认多页内容规划。</p></div>{error && <div className="notice error">{error}</div>}{projects.length === 0 ? <div className="empty-state">还没有商品项目，先创建一个项目。</div> : <div className="table-wrap"><table><thead><tr><th>项目</th><th>SKU / 型号</th><th>品类</th><th>状态</th><th>创建时间</th><th /></tr></thead><tbody>{projects.map((project) => <tr key={project.id}><td><strong>{project.name}</strong><small>{project.profile.name}</small></td><td>{project.profile.sku}<small>{project.profile.model || "未填写型号"}</small></td><td>{project.profile.category}</td><td><StatusBadge status={project.status} /></td><td>{formatDate(project.created_at)}</td><td><div className="table-actions"><button className="table-action" disabled={!!busy} onClick={() => void clone(project)}>{busy === project.id ? "复制中…" : "复制"}</button><button className="table-action" onClick={() => onOpen(project.id)}>进入项目 →</button></div></td></tr>)}</tbody></table></div>}</section>;
}

function BatchTable({ batches, onOpenProject, onRefresh }: { batches: Batch[]; onOpenProject: (id: string) => void; onRefresh: () => Promise<void> }) {
  const [recipes, setRecipes] = useState<Recipe[]>([]);
  useEffect(() => { void api.listRecipes().then((rows) => setRecipes(rows.filter((item) => item.status === "published"))); }, []);
  return <section className="panel"><div className="panel-heading"><h3>批量生产</h3><p>支持导入、批量生产、失败隔离、暂停继续、失败重试和按 SKU 导出。</p></div>{batches.length === 0 ? <div className="empty-state">还没有批量任务，可先导入一份 SKU 表格。</div> : <div className="batch-grid">{batches.map((batch) => <BatchCard key={batch.id} batch={batch} recipes={recipes} onOpenProject={onOpenProject} onRefresh={onRefresh} />)}</div>}</section>;
}

function BatchCard({ batch, recipes, onOpenProject, onRefresh }: { batch: Batch; recipes: Recipe[]; onOpenProject: (id: string) => void; onRefresh: () => Promise<void> }) {
  const [busy, setBusy] = useState(""); const [error, setError] = useState(""); const [downloadUrl, setDownloadUrl] = useState("");
  const [recipeId, setRecipeId] = useState(String(batch.common_config.recipe_id ?? "commerce-detail-v1"));
  const done = batch.progress.completed ?? 0; const total = batch.progress.total ?? batch.items.length; const percent = total ? Math.round(done / total * 100) : 0;
  async function action(kind: "start" | "retry" | "pause" | "resume" | "export") { setBusy(kind); setError(""); try { if (kind === "start") await api.startBatchProduction(batch.id, false, recipeId); if (kind === "retry") await api.startBatchProduction(batch.id, true, recipeId); if (kind === "pause") await api.pauseBatch(batch.id); if (kind === "resume") await api.resumeBatch(batch.id); if (kind === "export") { const result = await api.exportBatch(batch.id); setDownloadUrl(api.resolveUrl(result.download_url)); } await onRefresh(); } catch (value) { setError(value instanceof Error ? value.message : "批次操作失败"); } finally { setBusy(""); } }
  return <article className="batch-card"><div className="batch-title"><div><h3>{batch.name}</h3><p>{total} 个 SKU</p></div><StatusBadge status={batch.status} /></div><select className="batch-recipe" aria-label="批次配方" value={recipeId} onChange={(event) => setRecipeId(event.target.value)}>{recipes.map((recipe) => <option key={recipe.id} value={recipe.id}>{recipe.name} V{recipe.version}</option>)}</select><div className="progress-track"><span style={{ width: `${percent}%` }} /></div><div className="batch-stats"><span>完成 {done}</span><span>待审核 {batch.progress.needs_review ?? 0}</span><span>失败 {batch.progress.failed ?? 0}</span><span>待处理 {batch.progress.pending ?? 0}</span></div><div className="sku-list">{batch.items.map((item) => <button className={`sku-${item.status}`} key={item.id} onClick={() => onOpenProject(item.project_id)}>{item.sku} · {statusLabel(item.status)}</button>)}</div>{error && <div className="notice error">{error}</div>}{downloadUrl && <div className="notice success"><a href={downloadUrl}>下载批量交付包</a></div>}<div className="batch-actions">{batch.status === "paused" ? <button className="secondary" disabled={!!busy} onClick={() => void action("resume")}>继续</button> : batch.status === "running" ? <button className="secondary" disabled={!!busy} onClick={() => void action("pause")}>暂停</button> : <button className="primary" disabled={!!busy} onClick={() => void action("start")}>批量生产</button>}{(batch.progress.failed ?? 0) > 0 && <button className="secondary" disabled={!!busy} onClick={() => void action("retry")}>仅重试失败项</button>}<button className="ghost-button" disabled={!!busy || done === 0} onClick={() => void action("export")}>导出已完成 SKU</button></div></article>;
}

function CatalogPanel() {
  const [templates, setTemplates] = useState<TemplateDefinition[]>([]); const [recipes, setRecipes] = useState<Recipe[]>([]); const [prompts, setPrompts] = useState<PromptVersion[]>([]);
  const [promptName, setPromptName] = useState(""); const [promptBody, setPromptBody] = useState("为{{product_name}}制作{{page_title}}页面，视觉目标：{{visual_goal}}"); const [recipeName, setRecipeName] = useState(""); const [recipePrompt, setRecipePrompt] = useState(""); const [error, setError] = useState("");
  const refresh = useCallback(async () => { const [rows, recipeRows, promptRows] = await Promise.all([api.listTemplates(), api.listRecipes(), api.listPrompts()]); setTemplates(rows); setRecipes(recipeRows); setPrompts(promptRows); if (!recipePrompt) setRecipePrompt(promptRows.find((item) => item.status === "published")?.id ?? ""); }, [recipePrompt]);
  useEffect(() => { void refresh(); }, []);
  async function createPrompt(event: FormEvent) { event.preventDefault(); setError(""); try { await api.createPrompt({ name: promptName, body: promptBody, variables: Array.from(promptBody.matchAll(/{{(\w+)}}/g), (match) => match[1]), change_note: "控制台创建" }); setPromptName(""); await refresh(); } catch (value) { setError(value instanceof Error ? value.message : "Prompt 创建失败"); } }
  async function createRecipe(event: FormEvent) { event.preventDefault(); setError(""); try { await api.createRecipe({ name: recipeName, prompt_version_id: recipePrompt, model: "local-preview", model_params: { size: "900x1200" }, template_ids: templates.map((item) => item.id), qa_policy: "commerce-basic-v1", candidate_count: 2 }); setRecipeName(""); await refresh(); } catch (value) { setError(value instanceof Error ? value.message : "配方创建失败"); } }
  return <div className="catalog-stack">{error && <div className="notice error">{error}</div>}<div className="catalog-layout"><section className="panel"><div className="panel-heading"><h3>固定页面模板</h3><p>P0 使用固定布局，文字安全区和适用页面类型由平台控制。</p></div><div className="template-grid">{templates.map((template) => <article key={template.id}><TemplatePreview item={{ id: template.id, order: 1, page_type: (template.page_types[0] ?? "hero") as PageItem["page_type"], title: template.name, body: "商品标题与核心卖点", visual_goal: "", template_id: template.id, status: "draft" }} template={template} /><p>{template.page_types.map(pageTypeLabel).join(" / ")} · 安全区 {Math.round(template.safe_area * 100)}%</p></article>)}</div></section><section className="panel recipe-panel"><div className="panel-heading"><h3>生成配方</h3><p>只有已发布配方能够进入生产。</p></div>{recipes.map((recipe) => <article className="recipe-card" key={recipe.id}><StatusBadge status={recipe.status} /><h3>{recipe.name}</h3><p>{recipe.model} · 每页 {recipe.candidate_count} 个候选</p><small>质检策略：{recipe.qa_policy}</small>{recipe.status === "draft" && <button className="secondary" onClick={() => void api.publishRecipe(recipe.id).then(refresh)}>发布配方</button>}</article>)}<form className="catalog-form" onSubmit={createRecipe}><h4>新建配方草稿</h4><input required value={recipeName} onChange={(event) => setRecipeName(event.target.value)} placeholder="配方名称" /><select required value={recipePrompt} onChange={(event) => setRecipePrompt(event.target.value)}>{prompts.filter((item) => item.status === "published").map((item) => <option key={item.id} value={item.id}>{item.name} V{item.version}</option>)}</select><button className="secondary">保存配方草稿</button></form></section></div><section className="panel prompt-panel"><div className="panel-heading"><h3>Prompt 版本</h3><p>保存变量、版本、变更说明和发布状态；生产记录会固定引用具体版本。</p></div><div className="prompt-layout"><div className="prompt-list">{prompts.map((prompt) => <article key={prompt.id}><div><StatusBadge status={prompt.status} /><strong>{prompt.name} · V{prompt.version}</strong></div><p>{prompt.body}</p><small>{prompt.variables.map((item) => `{{${item}}}`).join(" · ") || "无变量"}</small>{prompt.status === "draft" && <button className="secondary" onClick={() => void api.publishPrompt(prompt.id).then(refresh)}>发布此版本</button>}</article>)}</div><form className="catalog-form" onSubmit={createPrompt}><h4>新建 Prompt 版本</h4><input required value={promptName} onChange={(event) => setPromptName(event.target.value)} placeholder="Prompt 名称" /><textarea required rows={8} value={promptBody} onChange={(event) => setPromptBody(event.target.value)} /><button className="primary">保存为草稿</button></form></div></section></div>;
}

function ProjectForm({ onClose, onCreated }: { onClose: () => void; onCreated: () => Promise<void> }) {
  const [projectName, setProjectName] = useState(""); const [profile, setProfile] = useState(emptyProfile()); const [sellingPoints, setSellingPoints] = useState(""); const [parameters, setParameters] = useState("容量=12kg"); const [error, setError] = useState(""); const [saving, setSaving] = useState(false);
  async function submit(event: FormEvent) { event.preventDefault(); setSaving(true); setError(""); try { const parsedParameters = Object.fromEntries(parameters.split(/\n|[;；]/).map((row) => row.trim()).filter(Boolean).map((row) => row.split(/[=：:]/, 2).map((part) => part.trim())).filter(([key, value]) => key && value)); await api.createProject({ project_name: projectName, profile: { ...profile, parameters: parsedParameters, selling_points: sellingPoints.split("\n").map((item) => item.trim()).filter(Boolean) } }); await onCreated(); } catch (reason) { setError(reason instanceof Error ? reason.message : "创建失败"); } finally { setSaving(false); } }
  return <Dialog title="新建商品项目" subtitle="先建立结构化商品档案，再上传素材并生成内容规划。" onClose={onClose}><form onSubmit={submit}><Field label="项目名称"><input required value={projectName} onChange={(e) => setProjectName(e.target.value)} placeholder="例如：X11 电商详情页" /></Field><div className="form-grid"><Field label="SKU"><input required value={profile.sku} onChange={(e) => setProfile({ ...profile, sku: e.target.value })} /></Field><Field label="型号"><input value={profile.model} onChange={(e) => setProfile({ ...profile, model: e.target.value })} /></Field><Field label="商品名称"><input required value={profile.name} onChange={(e) => setProfile({ ...profile, name: e.target.value })} /></Field><Field label="品类"><input required value={profile.category} onChange={(e) => setProfile({ ...profile, category: e.target.value })} /></Field></div><Field label="核心卖点（每行一项）"><textarea rows={3} value={sellingPoints} onChange={(e) => setSellingPoints(e.target.value)} /></Field><Field label="商品参数（每行：名称=值）"><textarea rows={3} value={parameters} onChange={(e) => setParameters(e.target.value)} /></Field>{error && <div className="notice error">{error}</div>}<FormActions onClose={onClose} saving={saving} label="创建项目" /></form></Dialog>;
}

function BatchForm({ onClose, onCreated }: { onClose: () => void; onCreated: () => Promise<void> }) {
  const [mode, setMode] = useState<"file" | "quick">("file"); const [name, setName] = useState(""); const [category, setCategory] = useState("洗衣机"); const [rows, setRows] = useState("X11|COLMO X11\nT1|COLMO T1"); const [file, setFile] = useState<File | null>(null); const [error, setError] = useState(""); const [saving, setSaving] = useState(false);
  async function submit(event: FormEvent) { event.preventDefault(); setSaving(true); setError(""); try { if (mode === "file") { if (!file) throw new Error("请选择 CSV 或 XLSX 文件"); await api.importBatch(name, file, category); } else { const skus = rows.split("\n").map((row) => row.trim()).filter(Boolean).map((row) => { const [sku, productName] = row.split("|").map((value) => value?.trim()); return { profile: { ...emptyProfile(), sku, name: productName || sku, category, model: sku }, override_config: {} }; }); await api.createBatch({ name, common_config: { recipe_id: "commerce-detail-v1" }, skus }); } await onCreated(); } catch (reason) { setError(reason instanceof Error ? reason.message : "创建失败"); } finally { setSaving(false); } }
  return <Dialog title="新建多 SKU 批次" subtitle="导入后，每个 SKU 会创建独立商品项目并共享基础配方。" onClose={onClose}><form onSubmit={submit}><div className="mode-switch"><button type="button" className={mode === "file" ? "active" : ""} onClick={() => setMode("file")}>表格导入</button><button type="button" className={mode === "quick" ? "active" : ""} onClick={() => setMode("quick")}>快速录入</button></div><Field label="批次名称"><input required value={name} onChange={(e) => setName(e.target.value)} /></Field><Field label="缺省品类"><input required value={category} onChange={(e) => setCategory(e.target.value)} /></Field>{mode === "file" ? <><Field label="SKU 文件（CSV / XLSX）"><label className="file-picker large"><input type="file" accept=".csv,.xlsx" onChange={(event) => setFile(event.target.files?.[0] ?? null)} /><span>{file?.name ?? "选择导入文件"}</span></label></Field><a className="template-download" href={api.batchImportTemplateUrl}>下载固定 CSV 模板</a></> : <Field label="SKU清单（每行：SKU|商品名称）"><textarea required rows={7} value={rows} onChange={(e) => setRows(e.target.value)} /></Field>}{error && <div className="notice error">{error}</div>}<FormActions onClose={onClose} saving={saving} label={mode === "file" ? "导入并创建" : "创建批次"} /></form></Dialog>;
}

function Metric({ label, value, hint, text = false }: { label: string; value: number | string; hint: string; text?: boolean }) { return <article className="metric-card"><p>{label}</p><strong className={text ? "metric-text" : ""}>{value}</strong><span>{hint}</span></article>; }
function Info({ label, value, wide = false }: { label: string; value: string; wide?: boolean }) { return <div className={wide ? "wide" : ""}><span>{label}</span><strong>{value}</strong></div>; }
function Dialog({ title, subtitle, onClose, children }: { title: string; subtitle: string; onClose: () => void; children: ReactNode }) { return <div className="dialog-backdrop" role="presentation" onMouseDown={(e) => e.target === e.currentTarget && onClose()}><section className="dialog" role="dialog" aria-modal="true"><button className="close" onClick={onClose}>×</button><p className="eyebrow">CREATE</p><h2>{title}</h2><p className="dialog-subtitle">{subtitle}</p>{children}</section></div>; }
function Field({ label, children }: { label: string; children: ReactNode }) { return <label className="field"><span>{label}</span>{children}</label>; }
function FormActions({ onClose, saving, label }: { onClose: () => void; saving: boolean; label: string }) { return <div className="form-actions"><button type="button" className="secondary" onClick={onClose}>取消</button><button className="primary" disabled={saving}>{saving ? "正在保存…" : label}</button></div>; }
function StatusBadge({ status }: { status: string }) { return <span className={`badge badge-${status}`}>{statusLabel(status)}</span>; }
function statusLabel(status: string) { return ({ draft: "草稿", ready: "待执行", queued: "排队中", running: "执行中", planned: "已策划", producing: "生产中", reviewing: "审核中", review: "需确认", pass: "通过", needs_review: "待审核", approved: "已确认", rejected: "不采用", completed: "已完成", partial_failed: "部分失败", paused: "已暂停", failed: "失败", archived: "已归档", published: "已发布", testing: "测试中", deprecated: "已停用", pending: "待处理" } as Record<string, string>)[status] ?? status; }
function formatDate(value: string) { return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(value)); }
function formatBytes(value: number) { return value < 1024 * 1024 ? `${Math.max(1, Math.round(value / 1024))} KB` : `${(value / 1024 / 1024).toFixed(1)} MB`; }
function tabTitle(tab: Tab) { return tab === "projects" ? "商品项目" : tab === "batches" ? "多 SKU 批量任务" : "模板与配方"; }
function pageTypeLabel(value: string) { return ({ hero: "主视觉", selling_point: "核心卖点", function: "功能说明", scene: "生活场景", parameters: "商品参数" } as Record<string, string>)[value] ?? value; }
function usageLabel(value: Asset["usage"]) { return ({ product: "商品外观", detail: "局部细节", brand: "品牌风格", scene: "场景参考" } as Record<Asset["usage"], string>)[value]; }

export default App;
