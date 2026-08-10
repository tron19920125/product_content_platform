import { FormEvent, ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import type { CSSProperties } from "react";
import {
  api,
  Asset,
  Batch,
  ImageCapabilities,
  PageItem,
  PagePlan,
  ProductionSnapshot,
  PromptVersion,
  ProductProfile,
  Project,
  Recipe,
  SystemPreflight,
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
  const [preflight, setPreflight] = useState<SystemPreflight | null>(null);

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
  useEffect(() => {
    let active = true;
    void api.getPreflight().then((result) => {
      if (active) setPreflight(result);
    }).catch(() => {
      if (active) setPreflight({
        status: "error",
        generation_mode: "local",
        qa_mode: "local",
        auth_mode: "unknown",
        checked_at: new Date().toISOString(),
        components: [{ name: "image_generation", status: "error", message: "环境预检接口连接失败。", endpoint_host: "" }],
      });
    });
    return () => { active = false; };
  }, []);

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
      <Sidebar tab={tab} role={role} preflight={preflight} setRole={(next) => { setRole(next); if (next === "business" && tab === "catalog") setTab("projects"); setSelectedProjectId(null); }} setTab={(next) => { setTab(next); setSelectedProjectId(null); }} />
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
          {loading ? <OperationFeedback label="正在连接本地服务" detail="正在读取项目与批次数据，请稍候。" /> : (
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

function Sidebar({ tab, role, preflight, setRole, setTab }: { tab: Tab; role: Role; preflight: SystemPreflight | null; setRole: (role: Role) => void; setTab: (tab: Tab) => void }) {
  return <aside className="sidebar">
    <div className="brand-mark">PC</div>
    <div><p className="eyebrow">PRODUCT CONTENT</p><h1>商品内容生产平台</h1></div>
    <nav>
      <button className={tab === "projects" ? "active" : ""} onClick={() => setTab("projects")}><span>01</span> 商品项目</button>
      <button className={tab === "batches" ? "active" : ""} onClick={() => setTab("batches")}><span>02</span> 批量任务</button>
      {role === "admin" && <button className={tab === "catalog" ? "active" : ""} onClick={() => setTab("catalog")}><span>03</span> 固定配置</button>}
    </nav>
    <div className="role-switch"><span>当前角色</span><select value={role} onChange={(event) => setRole(event.target.value as Role)}><option value="business">业务用户</option><option value="admin">管理员 / 专家</option></select></div>
    <SystemStatus preflight={preflight} />
  </aside>;
}

function SystemStatus({ preflight }: { preflight: SystemPreflight | null }) {
  if (!preflight) return <div className="sidebar-foot"><span className="status-dot pending" /> 正在检查运行环境</div>;
  const label = preflight.status === "ready" ? "Azure 环境已就绪" : preflight.status === "local" ? "本地演示模式" : "环境配置需处理";
  return <details className={`system-status ${preflight.status}`}>
    <summary><span className={`status-dot ${preflight.status}`} />{label}</summary>
    <p>生图：{preflight.generation_mode} · 质检：{preflight.qa_mode}</p>
    <ul>{preflight.components.map((item) => <li key={item.name}><b>{preflightComponentLabel(item.name)}</b><span>{item.message}</span></li>)}</ul>
  </details>;
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
  const productionJobs = production?.pages.flatMap((row) => row.job ? [row.job] : []) ?? [];
  const hasActiveProduction = productionJobs.some((job) => ["queued", "running"].includes(job.status));
  const workspaceStatus = hasActiveProduction
    ? "producing"
    : productionJobs.length > 0 && productionJobs.every((job) => job.status === "failed")
      ? "failed"
      : project?.status ?? "draft";

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
    if (!hasActiveProduction && project?.status !== "producing") return;
    const timer = window.setTimeout(() => {
      void api.getProduction(projectId).then(async (next) => {
        setProduction(next);
        const active = next.pages.some((row) => row.job && ["queued", "running"].includes(row.job.status));
        if (!active) {
          const projectRow = await api.getProject(projectId);
          setProject(projectRow);
          await onChanged();
        }
      }).catch((reason) => setError(reason instanceof Error ? reason.message : "生产进度刷新失败"));
    }, 1200);
    return () => window.clearTimeout(timer);
  }, [hasActiveProduction, production, project?.status, projectId, onChanged]);

  async function generatePlan() {
    setBusy("generate"); setError(""); setMessage("");
    try {
      const nextPlan = await api.generatePlan(projectId);
      const [projectRow] = await Promise.all([api.getProject(projectId), onChanged()]);
      setPlan(nextPlan); setProject(projectRow); setProduction(null);
      setMessage("已生成新的五页规划草稿；请检查并确认规划，然后再启动图片生产。");
    }
    catch (reason) { setError(reason instanceof Error ? reason.message : "生成失败"); }
    finally { setBusy(""); }
  }

  async function savePlan(confirmed: boolean) {
    if (!plan) return;
    setBusy(confirmed ? "confirm" : "save"); setError(""); setMessage("");
    try {
      const saved = await api.savePlan(projectId, { items: plan.items, confirmed });
      const [productionRow, projectRow] = await Promise.all([
        api.getProduction(projectId), api.getProject(projectId), onChanged(),
      ]);
      setPlan(saved);
      setProduction(productionRow);
      setMessage(confirmed ? "页面规划已确认，可以进入生产阶段" : "页面规划草稿已保存");
      setProject(projectRow);
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

  if (loading || !project) return <main><OperationFeedback label="正在加载项目工作台" detail="正在同步商品档案、内容规划和生产状态。" /></main>;
  return <main className="project-workspace">
    <header className="topbar workspace-topbar">
      <div><button className="back-button" onClick={onBack}>← 返回项目</button><p className="eyebrow">{project.profile.sku} · {project.profile.category}</p><h2>{project.name}</h2></div>
      <StatusBadge status={workspaceStatus} />
    </header>
    <div className="workflow-strip">
      <span className="done">1 商品资料</span><i>→</i><span className={plan ? "done" : "active"}>2 内容规划</span><i>→</i><span className={plan?.confirmed ? "done" : ""}>3 固定配方</span><i>→</i><span className={production?.pages.some((row) => row.candidates.length) ? "done" : ""}>4 图片生产与质检</span>
    </div>
    {error && <div className="notice error">{error}</div>}
    {message && <div className="notice success">{message}</div>}
    {busy && <OperationFeedback label={projectOperationLabel(busy)} detail="操作完成前请保持当前页面打开。" compact />}

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
          <button className={plan ? "ghost-button" : "primary"} disabled={!!busy} onClick={() => void generatePlan()}>{busy === "generate" ? "生成规划中…" : plan ? "重新生成规划" : "生成内容规划"}</button>
        </div>
      </div>
      {!plan ? <div className="empty-state inline-empty">录入卖点和参数后，可生成一套五页内容结构。</div> : <div className="plan-list">
        <div className="recipe-banner"><div><span>可用配方</span><strong>{recipes.filter((item) => item.status === "published").length} 套已发布配方</strong></div><small>在生产阶段选择配方，生成记录会锁定具体版本</small></div>
        {plan.items.map((item, index) => <PageEditor key={item.id} item={item} templates={templates} onChange={(patch) => updatePage(index, patch)} onMoveUp={() => movePage(index, -1)} onMoveDown={() => movePage(index, 1)} onDelete={() => deletePage(index)} first={index === 0} last={index === plan.items.length - 1} />)}
      </div>}
    </section>
    {plan && !plan.confirmed && <div className="production-gate" role="status"><span>下一步</span><div><strong>图片生产尚未开始</strong><p>当前是规划草稿。请先检查页面内容并点击“确认规划”，确认后才会显示生产按钮和实时进度。</p></div></div>}
    {plan?.confirmed && <ProductionPanel projectId={projectId} recipes={recipes} referenceAssets={assets.filter((item) => item.mime_type.startsWith("image/"))} snapshot={production} onRefresh={async () => { setProduction(await api.getProduction(projectId)); setProject(await api.getProject(projectId)); await onChanged(); }} />}
    {editingProfile && <ProfileEditor project={project} onClose={() => setEditingProfile(false)} onSaved={async () => { setEditingProfile(false); await load(); await onChanged(); setMessage("商品档案已更新，再次确认页面规划后可重新生产"); }} />}
  </main>;
}

function AssetPanel({ projectId, assets, onUploaded }: { projectId: string; assets: Asset[]; onUploaded: () => Promise<void> }) {
  const [file, setFile] = useState<File | null>(null);
  const [usage, setUsage] = useState<Asset["usage"]>("product");
  const [authorizationStatus, setAuthorizationStatus] = useState<Asset["authorization_status"]>("unconfirmed");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [uploadedFileName, setUploadedFileName] = useState("");
  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!file) return;
    const form = event.currentTarget;
    setBusy(true); setError(""); setUploadedFileName("");
    try {
      const uploaded = await api.uploadAsset(projectId, file, usage, authorizationStatus);
      form.reset();
      setFile(null);
      setUploadedFileName(uploaded.file_name);
      await onUploaded();
    }
    catch (reason) { setError(reason instanceof Error ? reason.message : "上传失败"); }
    finally { setBusy(false); }
  }
  return <article className="panel compact-panel">
    <div className="panel-heading"><h3>参考素材</h3><p>支持商品、细节、品牌和场景参考，单文件不超过 25MB。</p></div>
    <form className="asset-upload" onSubmit={upload}>
      <select value={usage} onChange={(event) => setUsage(event.target.value as Asset["usage"])}><option value="product">商品外观</option><option value="detail">局部细节</option><option value="brand">品牌风格</option><option value="scene">场景参考</option></select>
      <select value={authorizationStatus} onChange={(event) => setAuthorizationStatus(event.target.value as Asset["authorization_status"])}><option value="unconfirmed">授权待确认</option><option value="authorized">已授权使用</option><option value="restricted">限制使用</option></select>
      <label className="file-picker"><input type="file" accept=".png,.jpg,.jpeg,.webp,.pdf" onChange={(event) => { setFile(event.target.files?.[0] ?? null); setUploadedFileName(""); setError(""); }} /><span>{file?.name ?? "选择素材文件"}</span></label>
      <button className="secondary" disabled={!file || busy}>{busy ? "上传绑定中…" : "上传并绑定"}</button>
    </form>
    {busy && <OperationFeedback label="正在上传素材" detail="正在保存文件并绑定到当前项目，完成前请勿开始生产。" compact />}
    {file && !busy && <div className="notice warning asset-notice">已选择 <strong>{file.name}</strong>，但尚未上传；当前生产任务不会使用此文件。请点击“上传并绑定”。</div>}
    {uploadedFileName && <div className="notice success asset-notice"><strong>{uploadedFileName}</strong> 已上传并绑定到当前项目，可用于下一次生产。</div>}
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
  const textBox = template?.text_box ?? [0.09, 0.07, 0.91, 0.29];
  const productBox = template?.product_anchor_box ?? template?.product_box ?? [0.20, 0.32, 0.80, 0.94];
  return <div className={`template-preview ${template?.layout ?? "center"}`} style={{ aspectRatio: `${template?.width ?? 2048} / ${template?.height ?? 2048}` }}><div className="preview-environment"><i /><b /><em /></div><div className="preview-copy" style={regionStyle(textBox)}><strong>{item.title}</strong><span>{item.body}</span></div><div className="product-shape" style={regionStyle(productBox)}><i /><b /></div><small>{template?.size ?? "2048x2048"} · {template?.name ?? item.template_id}</small></div>;
}

function ProductionPanel({ projectId, recipes, referenceAssets, snapshot, onRefresh }: { projectId: string; recipes: Recipe[]; referenceAssets: Asset[]; snapshot: ProductionSnapshot | null; onRefresh: () => Promise<void> }) {
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [downloadUrl, setDownloadUrl] = useState("");
  const publishedRecipes = recipes.filter((item) => item.status === "published");
  const [recipeId, setRecipeId] = useState(publishedRecipes[0]?.id ?? "commerce-detail-v1");
  const selectedRecipe = publishedRecipes.find((item) => item.id === recipeId) ?? publishedRecipes[0];
  const recipeDefaultQuality = recipeQuality(selectedRecipe);
  const [quality, setQuality] = useState(recipeDefaultQuality);
  const [message, setMessage] = useState("");
  const pages = snapshot?.pages ?? [];
  const hasResults = pages.some((row) => row.candidates.length > 0);
  const hasJobs = pages.some((row) => row.job !== null);
  const activeJobs = pages.filter((row) => row.job && ["queued", "running"].includes(row.job.status)).length;
  const failedJobs = pages.filter((row) => row.job?.status === "failed").length;
  const completedJobs = pages.filter((row) => row.job?.status === "completed").length;
  const isProductionActive = activeJobs > 0;
  const canExport = snapshot?.ready_for_export ?? false;
  const immediateActionLabel = productionActionLabel(busy);
  const referenceUrl = referenceAssets[0] ? api.assetUrl(referenceAssets[0].id) : "";
  useEffect(() => {
    if (!publishedRecipes.length || publishedRecipes.some((item) => item.id === recipeId)) return;
    const first = publishedRecipes[0];
    setRecipeId(first.id);
    setQuality(recipeQuality(first));
  }, [publishedRecipes, recipeId]);
  async function start(force: boolean) {
    setBusy(force ? "regenerate" : "start"); setError(""); setMessage(""); setDownloadUrl("");
    try {
      await api.startProduction(projectId, force, recipeId, quality === recipeDefaultQuality ? undefined : quality);
      setMessage(force ? `生产任务已按 ${qualityLabel(quality)} 质量重新提交，进度会自动更新。` : `生产任务已按 ${qualityLabel(quality)} 质量提交，正在生成图片并执行质检。`);
      await onRefresh();
    }
    catch (reason) { setError(reason instanceof Error ? reason.message : "生产任务启动失败"); }
    finally { setBusy(""); }
  }
  async function exportResult() {
    setBusy("export"); setError("");
    try { const result = await api.exportProject(projectId); setDownloadUrl(api.resolveUrl(result.download_url)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "导出失败"); }
    finally { setBusy(""); }
  }
  async function recompose(pageId: string) { setBusy(`recompose-${pageId}`); setError(""); setMessage(""); try { await api.recomposePage(projectId, pageId); setMessage("页面已重新排版并完成质检。"); await onRefresh(); } catch (reason) { setError(reason instanceof Error ? reason.message : "重新排版失败"); } finally { setBusy(""); } }
  async function regenerate(pageId: string) { setBusy(`regenerate-${pageId}`); setError(""); setMessage(""); try { await api.regeneratePage(projectId, pageId, recipeId, quality === recipeDefaultQuality ? undefined : quality); setMessage(`单页已按 ${qualityLabel(quality)} 质量重新提交。`); await onRefresh(); } catch (reason) { setError(reason instanceof Error ? reason.message : "单页重生成失败"); } finally { setBusy(""); } }
  async function saveAsRecipe() { setBusy("recipe"); setError(""); try { const recipe = await api.createRecipeCandidate(projectId, `${snapshot?.project.profile.sku ?? "商品"}验证配方`); setMessage(`已生成配方草稿：${recipe.name}，请到固定配置中测试并发布。`); } catch (reason) { setError(reason instanceof Error ? reason.message : "配方沉淀失败"); } finally { setBusy(""); } }
  return <section className="panel production-panel">
    <div className="panel-heading planning-heading"><div><h3>图片生产、质检与审核</h3><p>配方提供默认质量；本次生产可以临时覆盖，不会修改原配方。</p></div><div className="production-controls"><div className="production-config"><label><span>生成配方</span><select aria-label="生成配方" value={recipeId} disabled={!!busy || isProductionActive} onChange={(event) => { const nextId = event.target.value; setRecipeId(nextId); setQuality(recipeQuality(publishedRecipes.find((item) => item.id === nextId))); }}>{publishedRecipes.map((recipe) => <option key={recipe.id} value={recipe.id}>{recipe.name} V{recipe.version}</option>)}</select></label><label><span>本次质量</span><select aria-label="本次生成质量" value={quality} disabled={!!busy || isProductionActive} onChange={(event) => setQuality(event.target.value)}><option value={recipeDefaultQuality}>按配方默认 · {qualityLabel(recipeDefaultQuality)}</option>{["low", "medium", "high"].filter((item) => item !== recipeDefaultQuality).map((item) => <option key={item} value={item}>{qualityLabel(item)}</option>)}</select></label></div><div className="button-row">{canExport && <button className="ghost-button" disabled={!!busy || isProductionActive} onClick={() => void saveAsRecipe()}>{busy === "recipe" ? "保存中…" : "沉淀为配方"}</button>}{hasResults && !isProductionActive && <button className="secondary" disabled={!!busy} onClick={() => void start(true)}>{busy === "regenerate" ? "重新生产中…" : "整套重新生产"}</button>}<button className="primary" disabled={!!busy || isProductionActive || (hasResults && !canExport && failedJobs === 0)} onClick={() => canExport ? void exportResult() : void start(failedJobs > 0)}>{busy === "start" || busy === "regenerate" ? "正在提交…" : busy === "export" ? "正在打包…" : isProductionActive ? "生产进行中…" : canExport ? "导出正式结果" : failedJobs > 0 ? "重试生产" : hasResults ? "等待确认后导出" : "开始生产"}</button></div></div></div>
    {referenceAssets.length > 0
      ? <div className="notice success reference-binding" role="status"><strong>已绑定 {referenceAssets.length} 张参考图</strong><span>本次生产会输入：{referenceAssets.map((asset) => asset.file_name).join("、")}</span></div>
      : <div className="notice warning reference-binding" role="status"><strong>未检测到已上传并绑定的参考图</strong><span>本次会使用纯文本生图。请先在上方“参考素材”区域选择图片并点击“上传并绑定”。</span></div>}
    {immediateActionLabel && <OperationFeedback label={immediateActionLabel} detail="请求正在提交，请勿重复点击。" compact />}
    {snapshot && hasJobs && <ProductionProgress total={pages.length} completed={completedJobs} failed={failedJobs} active={activeJobs} />}
    {error && <div className="notice error">{error}</div>}
    {message && <div className="notice success">{message}</div>}
    {downloadUrl && <div className="notice success">正式结果已生成：<a href={downloadUrl}>下载 ZIP 交付包</a></div>}
    {!snapshot || !hasJobs ? <div className="empty-state inline-empty">确认规划后即可开始生产；提交后这里会显示实时进度。</div> : <div className="production-pages">{snapshot.pages.map((row) => <article className="production-page" key={row.page.id}><div className="production-page-head"><div><span>第 {row.page.order} 页 · {pageTypeLabel(row.page.page_type)}</span><h4>{row.page.title}</h4></div><div>{row.candidates.length > 0 && <><button className="ghost-button mini" disabled={!!busy || isProductionActive} onClick={() => void recompose(row.page.id)}>{busy === `recompose-${row.page.id}` ? "排版中…" : "仅重新排版"}</button><button className="ghost-button mini" disabled={!!busy || isProductionActive} onClick={() => void regenerate(row.page.id)}>{busy === `regenerate-${row.page.id}` ? "重生成中…" : "重新生成本页"}</button></>}{row.job && <StatusBadge status={row.job.status} />}{row.decision?.decision === "approved" && <StatusBadge status="approved" />}</div></div><PageJobState job={row.job} candidates={row.candidates} />{row.job?.error && <div className="notice error">{row.job.error}</div>}<div className="candidate-grid">{row.candidates.map((candidate) => <CandidateCard key={candidate.id} candidate={candidate} referenceUrl={referenceUrl} selected={row.decision?.candidate_id === candidate.id && row.decision.decision === "approved"} onReviewed={onRefresh} />)}</div></article>)}</div>}
  </section>;
}

function ProductionProgress({ total, completed, failed, active }: { total: number; completed: number; failed: number; active: number }) {
  const processed = completed + failed;
  const queued = Math.max(0, total - processed - active);
  const percent = total ? Math.round(processed / total * 100) : 0;
  const title = active > 0 ? "生产与质检正在进行" : failed > 0 ? "生产已结束，存在失败页面" : "图片生产已完成";
  return <div className={`production-progress ${failed > 0 && active === 0 ? "has-error" : ""}`} role="status" aria-live="polite">
    <div className="progress-heading"><div><span className={active > 0 ? "spinner" : "progress-status-dot"} aria-hidden="true" /><div><strong>{title}</strong><small>进度按页面计算，页面内部还会依次完成生图、OCR 与 LLM 质检。</small></div></div><b>{percent}%</b></div>
    <div className="progress-track production-progress-track" role="progressbar" aria-label="生产进度" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent}><span style={{ width: `${percent}%` }} /></div>
    <div className="production-stats"><span>已完成 <b>{completed}</b></span><span>处理中 <b>{active}</b></span><span>排队 <b>{queued}</b></span><span className={failed ? "failed" : ""}>失败 <b>{failed}</b></span><span>共 {total} 页</span></div>
  </div>;
}

function PageJobState({ job, candidates }: { job: ProductionSnapshot["pages"][number]["job"]; candidates: ProductionSnapshot["pages"][number]["candidates"] }) {
  const startedAt = typeof job?.trace.started_at === "string" ? job.trace.started_at : "";
  const candidateReferenceCount = candidates.some((candidate) => {
    const generator = candidate.metadata?.generator as Record<string, unknown> | undefined;
    return typeof generator?.source_reference === "string" && generator.source_reference.length > 0;
  }) ? 1 : 0;
  const referenceCount = typeof job?.trace.reference_count === "number" ? job.trace.reference_count : candidateReferenceCount;
  const referenceState = referenceCount > 0 ? `已输入 ${referenceCount} 张参考图` : "未输入参考图";
  const candidateCount = candidates.length;
  const [clock, setClock] = useState(() => Date.now());
  useEffect(() => {
    if (job?.status !== "running" || !startedAt) return;
    setClock(Date.now());
    const timer = window.setInterval(() => setClock(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [job?.status, startedAt]);
  const elapsedSeconds = startedAt
    ? Math.max(0, Math.floor((clock - Date.parse(startedAt)) / 1000))
    : 0;
  if (!job) return null;
  if (job.status === "running") return <div className="page-job-state running" role="status"><span className="spinner" aria-hidden="true" /><div><strong>正在生成图片并执行质检</strong><small>{referenceState} · 第 {job.attempt}/{job.max_attempts} 次尝试 · 已运行 {formatElapsed(elapsedSeconds)}，正在等待 Azure 返回。单页高质量生图可能需要数分钟。</small></div><div className="indeterminate-track"><i /></div></div>;
  if (job.status === "queued") return <div className="page-job-state queued" role="status"><span className="queue-dot" aria-hidden="true" /><div><strong>等待处理</strong><small>{referenceState} · 前面的页面完成后会自动开始。</small></div></div>;
  if (job.status === "completed") return <div className="page-job-state completed"><span className="progress-status-dot" aria-hidden="true" /><div><strong>生成与质检已完成</strong><small>{referenceState} · 已生成 {candidateCount} 个候选，请选择并确认最终图片。</small></div></div>;
  return <div className="page-job-state failed"><span aria-hidden="true">!</span><div><strong>本页生产失败</strong><small>可查看下方错误详情，修复后点击“重试生产”。</small></div></div>;
}

function formatElapsed(totalSeconds: number) {
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return minutes > 0 ? `${minutes}分${String(seconds).padStart(2, "0")}秒` : `${seconds}秒`;
}

function CandidateCard({ candidate, referenceUrl, selected, onReviewed }: { candidate: ProductionSnapshot["pages"][number]["candidates"][number]; referenceUrl: string; selected: boolean; onReviewed: () => Promise<void> }) {
  const [reason, setReason] = useState(""); const [busy, setBusy] = useState(false); const [error, setError] = useState(""); const [showQaOverlay, setShowQaOverlay] = useState(false);
  const blocking = candidate.qa?.issues.some((issue) => ["P0", "P1"].includes(issue.severity));
  const layout = candidate.qa?.evidence?.layout as { canvas?: number[]; safe_area?: number[]; text_bbox?: number[]; subject_bbox?: number[] } | undefined;
  const overlay = (bbox?: number[]) => { const canvas = layout?.canvas ?? [900, 1200]; return bbox?.length === 4 ? { left: `${bbox[0] / canvas[0] * 100}%`, top: `${bbox[1] / canvas[1] * 100}%`, width: `${(bbox[2] - bbox[0]) / canvas[0] * 100}%`, height: `${(bbox[3] - bbox[1]) / canvas[1] * 100}%` } : undefined; };
  async function review(decision: "approved" | "rejected") { setBusy(true); setError(""); try { await api.reviewCandidate(candidate.id, decision, reason); await onReviewed(); } catch (value) { setError(value instanceof Error ? value.message : "审核失败"); } finally { setBusy(false); } }
  return <div className={`candidate-card ${selected ? "selected" : ""}`}>
    <div className="candidate-image">
      <img src={api.resolveUrl(candidate.composed_url)} alt={`候选 ${candidate.candidate_index}`} />
      {showQaOverlay && <>
        {layout?.safe_area && <i className="qa-box safe" style={overlay(layout.safe_area)} />}
        {layout?.subject_bbox && <i className="qa-box subject" style={overlay(layout.subject_bbox)} />}
        {layout?.text_bbox && <i className="qa-box text" style={overlay(layout.text_bbox)} />}
      </>}
      <span>排名 #{candidate.rank}</span>
      {layout && <button type="button" className={`qa-overlay-toggle ${showQaOverlay ? "active" : ""}`} aria-pressed={showQaOverlay} onClick={() => setShowQaOverlay((visible) => !visible)}>{showQaOverlay ? "隐藏质检框" : "显示质检框"}</button>}
      {referenceUrl && <div className="reference-thumb"><img src={referenceUrl} alt="商品参考图" /><small>参考图</small></div>}
    </div>
    <div className="candidate-summary">
      <div><strong>{candidate.score} 分</strong><StatusBadge status={candidate.qa?.status ?? "review"} /></div>
      {candidate.qa?.issues.length ? <ul className="qa-issue-list">{candidate.qa.issues.map((issue, index) => <li key={`${issue.code}-${index}`} className={`severity-${issue.severity.toLowerCase()}`}><b>{issue.severity}</b><span>{issue.message}</span></li>)}</ul> : <p>未发现阻塞问题</p>}
      <details className="qa-severity-legend"><summary>P0 / P1 / P2 / P3 是什么？</summary><p><b>P0</b> 系统硬性阻断；<b>P1</b> 重大问题，会阻止直接确认；<b>P2</b> 需要关注或人工确认；<b>P3</b> 提示或轻微建议。</p></details>
      {candidate.qa?.repair_applied && <small>已执行自动排版或一轮图片修复</small>}
      <details><summary>查看分层文件与质检证据</summary>
        <div className="layer-links">
          {candidate.background_url && <a href={api.resolveUrl(candidate.background_url)} target="_blank" rel="noreferrer">场景背景</a>}
          {candidate.product_layer_url && <a href={api.resolveUrl(candidate.product_layer_url)} target="_blank" rel="noreferrer">原样商品层</a>}
          <a href={api.resolveUrl(candidate.base_url)} target="_blank" rel="noreferrer">无字底图</a>
          <a href={api.resolveUrl(candidate.text_layer_url)} target="_blank" rel="noreferrer">文字层</a>
          <a href={api.resolveUrl(candidate.composed_url)} target="_blank" rel="noreferrer">最终合成图</a>
        </div>
        <pre>{JSON.stringify(candidate.qa?.evidence, null, 2)}</pre>
      </details>
      {blocking && <input className="override-input" value={reason} onChange={(event) => setReason(event.target.value)} placeholder="P0/P1 人工覆盖原因（必填）" />}
      {busy && <OperationFeedback label="正在提交审核结果" compact />}
      {error && <div className="notice error">{error}</div>}
      <div className="candidate-actions"><button className="secondary" disabled={busy} onClick={() => void review("rejected")}>{busy ? "提交中…" : "不采用"}</button><button className="primary" disabled={busy || selected} onClick={() => void review("approved")}>{busy ? "提交中…" : selected ? "已确认" : "确认此图"}</button></div>
    </div>
  </div>;
}

function ProjectTable({ projects, onOpen, onRefresh }: { projects: Project[]; onOpen: (id: string) => void; onRefresh: () => Promise<void> }) {
  const [busy, setBusy] = useState(""); const [error, setError] = useState("");
  async function clone(project: Project) { setBusy(project.id); setError(""); try { const copied = await api.cloneProject(project.id); await onRefresh(); onOpen(copied.id); } catch (reason) { setError(reason instanceof Error ? reason.message : "复制失败"); } finally { setBusy(""); } }
  return <section className="panel"><div className="panel-heading"><h3>最近项目</h3><p>进入项目后上传素材、生成并确认多页内容规划。</p></div>{busy && <OperationFeedback label="正在复制项目" detail="正在复制商品档案与页面规划。" compact />}{error && <div className="notice error">{error}</div>}{projects.length === 0 ? <div className="empty-state">还没有商品项目，先创建一个项目。</div> : <div className="table-wrap"><table><thead><tr><th>项目</th><th>SKU / 型号</th><th>品类</th><th>状态</th><th>创建时间</th><th /></tr></thead><tbody>{projects.map((project) => <tr key={project.id}><td><strong>{project.name}</strong><small>{project.profile.name}</small></td><td>{project.profile.sku}<small>{project.profile.model || "未填写型号"}</small></td><td>{project.profile.category}</td><td><StatusBadge status={project.status} /></td><td>{formatDate(project.created_at)}</td><td><div className="table-actions"><button className="table-action" disabled={!!busy} onClick={() => void clone(project)}>{busy === project.id ? "复制中…" : "复制"}</button><button className="table-action" disabled={!!busy} onClick={() => onOpen(project.id)}>进入项目 →</button></div></td></tr>)}</tbody></table></div>}</section>;
}

function BatchTable({ batches, onOpenProject, onRefresh }: { batches: Batch[]; onOpenProject: (id: string) => void; onRefresh: () => Promise<void> }) {
  const [recipes, setRecipes] = useState<Recipe[]>([]);
  useEffect(() => { void api.listRecipes().then((rows) => setRecipes(rows.filter((item) => item.status === "published"))); }, []);
  return <section className="panel"><div className="panel-heading"><h3>批量生产</h3><p>支持导入、批量生产、失败隔离、暂停继续、失败重试和按 SKU 导出。</p></div>{batches.length === 0 ? <div className="empty-state">还没有批量任务，可先导入一份 SKU 表格。</div> : <div className="batch-grid">{batches.map((batch) => <BatchCard key={batch.id} batch={batch} recipes={recipes} onOpenProject={onOpenProject} onRefresh={onRefresh} />)}</div>}</section>;
}

function BatchCard({ batch, recipes, onOpenProject, onRefresh }: { batch: Batch; recipes: Recipe[]; onOpenProject: (id: string) => void; onRefresh: () => Promise<void> }) {
  const [busy, setBusy] = useState(""); const [error, setError] = useState(""); const [downloadUrl, setDownloadUrl] = useState("");
  const [recipeId, setRecipeId] = useState(String(batch.common_config.recipe_id ?? "commerce-detail-v1"));
  const [quality, setQuality] = useState(recipeQuality(recipes.find((item) => item.id === recipeId)));
  const batchRecipeQuality = recipeQuality(recipes.find((item) => item.id === recipeId));
  useEffect(() => {
    const selected = recipes.find((item) => item.id === recipeId);
    if (selected) setQuality(recipeQuality(selected));
  }, [recipeId, recipes]);
  const done = batch.progress.completed ?? 0; const total = batch.progress.total ?? batch.items.length; const percent = total ? Math.round(done / total * 100) : 0;
  async function action(kind: "start" | "retry" | "pause" | "resume" | "export") { setBusy(kind); setError(""); try { if (kind === "start") await api.startBatchProduction(batch.id, false, recipeId, quality === batchRecipeQuality ? undefined : quality); if (kind === "retry") await api.startBatchProduction(batch.id, true, recipeId, quality === batchRecipeQuality ? undefined : quality); if (kind === "pause") await api.pauseBatch(batch.id); if (kind === "resume") await api.resumeBatch(batch.id); if (kind === "export") { const result = await api.exportBatch(batch.id); setDownloadUrl(api.resolveUrl(result.download_url)); } await onRefresh(); } catch (value) { setError(value instanceof Error ? value.message : "批次操作失败"); } finally { setBusy(""); } }
  return <article className="batch-card"><div className="batch-title"><div><h3>{batch.name}</h3><p>{total} 个 SKU</p></div><StatusBadge status={batch.status} /></div><div className="batch-config"><select className="batch-recipe" aria-label="批次配方" value={recipeId} disabled={!!busy} onChange={(event) => { setRecipeId(event.target.value); setQuality(recipeQuality(recipes.find((item) => item.id === event.target.value))); }}>{recipes.map((recipe) => <option key={recipe.id} value={recipe.id}>{recipe.name} V{recipe.version}</option>)}</select><select aria-label="批次生成质量" value={quality} disabled={!!busy} onChange={(event) => setQuality(event.target.value)}>{["low", "medium", "high"].map((item) => <option key={item} value={item}>{qualityLabel(item)}</option>)}</select></div><div className="progress-track" role="progressbar" aria-label={`${batch.name}批次进度`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent}><span style={{ width: `${percent}%` }} /></div><div className="batch-stats"><span>完成 {done}</span><span>待审核 {batch.progress.needs_review ?? 0}</span><span>失败 {batch.progress.failed ?? 0}</span><span>待处理 {batch.progress.pending ?? 0}</span></div><div className="sku-list">{batch.items.map((item) => <button className={`sku-${item.status}`} key={item.id} onClick={() => onOpenProject(item.project_id)}>{item.sku} · {statusLabel(item.status)}</button>)}</div>{busy && <OperationFeedback label={batchOperationLabel(busy)} detail="请求完成后批次状态会自动刷新。" compact />}{error && <div className="notice error">{error}</div>}{downloadUrl && <div className="notice success"><a href={downloadUrl}>下载批量交付包</a></div>}<div className="batch-actions">{batch.status === "paused" ? <button className="secondary" disabled={!!busy} onClick={() => void action("resume")}>{busy === "resume" ? "继续中…" : "继续"}</button> : batch.status === "running" ? <button className="secondary" disabled={!!busy} onClick={() => void action("pause")}>{busy === "pause" ? "暂停中…" : "暂停"}</button> : <button className="primary" disabled={!!busy} onClick={() => void action("start")}>{busy === "start" ? "提交中…" : "批量生产"}</button>}{(batch.progress.failed ?? 0) > 0 && <button className="secondary" disabled={!!busy} onClick={() => void action("retry")}>{busy === "retry" ? "重试中…" : "仅重试失败项"}</button>}<button className="ghost-button" disabled={!!busy || done === 0} onClick={() => void action("export")}>{busy === "export" ? "打包中…" : "导出已完成 SKU"}</button></div></article>;
}

function CatalogPanel() {
  const [templates, setTemplates] = useState<TemplateDefinition[]>([]);
  const [recipes, setRecipes] = useState<Recipe[]>([]);
  const [prompts, setPrompts] = useState<PromptVersion[]>([]);
  const [capabilities, setCapabilities] = useState<ImageCapabilities | null>(null);
  const [promptName, setPromptName] = useState("");
  const [promptBody, setPromptBody] = useState("为{{product_name}}制作高端电商视觉底图。页面目标：{{visual_goal}}。生成真实空间、自然光、材质层次和克制的辅助陈设。{{scene_prompt_hint}}。{{composition_instruction}}。最终文字由后期排版，底图不要生成营销文字。");
  const [recipeName, setRecipeName] = useState("");
  const [recipePrompt, setRecipePrompt] = useState("");
  const [newRecipeQuality, setNewRecipeQuality] = useState("high");
  const [newRecipeReferenceStrategy, setNewRecipeReferenceStrategy] = useState("layered_product");
  const [newRecipeAutoRepair, setNewRecipeAutoRepair] = useState("0");
  const [recipeCandidates, setRecipeCandidates] = useState(1);
  const [recipeTemplates, setRecipeTemplates] = useState<string[]>([]);
  const [templateName, setTemplateName] = useState("");
  const [templateBase, setTemplateBase] = useState("");
  const [templatePageType, setTemplatePageType] = useState<PageItem["page_type"]>("scene");
  const [templateSize, setTemplateSize] = useState("2048x2048");
  const [customWidth, setCustomWidth] = useState("2048");
  const [customHeight, setCustomHeight] = useState("2048");
  const [previewTemplateId, setPreviewTemplateId] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");

  const refresh = useCallback(async () => {
    const [templateRows, recipeRows, promptRows, imageCapabilities] = await Promise.all([
      api.listTemplates(), api.listRecipes(), api.listPrompts(), api.getImageCapabilities(),
    ]);
    setTemplates(templateRows);
    setRecipes(recipeRows);
    setPrompts(promptRows);
    setCapabilities(imageCapabilities);
    setRecipePrompt((current) => current || promptRows.find((item) => item.status === "published")?.id || "");
    setRecipeTemplates((current) => current.length ? current : templateRows.map((item) => item.id));
    setTemplateBase((current) => current || templateRows.find((item) => item.id === "scene-overlay")?.id || templateRows[0]?.id || "");
    setPreviewTemplateId((current) => current || templateRows[0]?.id || "");
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const publishedPrompts = prompts.filter((item) => item.status === "published");
  const selectedPrompt = prompts.find((item) => item.id === recipePrompt) ?? publishedPrompts[0];
  const previewTemplate = templates.find((item) => item.id === previewTemplateId) ?? templates[0];
  const effectiveTemplateSize = templateSize === "custom" ? `${customWidth}x${customHeight}` : templateSize;
  const activeModel = recipes.find((item) => item.status === "published")?.model ?? "azure-gpt-image";

  async function createTemplate(event: FormEvent) {
    event.preventDefault(); setBusy("create-template"); setError("");
    try {
      await api.createTemplate({ name: templateName, page_types: [templatePageType], base_template_id: templateBase, size: effectiveTemplateSize });
      setTemplateName("");
      await refresh();
    } catch (value) { setError(value instanceof Error ? value.message : "模板创建失败"); }
    finally { setBusy(""); }
  }

  async function createPrompt(event: FormEvent) {
    event.preventDefault(); setBusy("create-prompt"); setError("");
    try {
      await api.createPrompt({ name: promptName, body: promptBody, variables: Array.from(promptBody.matchAll(/{{(\w+)}}/g), (match) => match[1]), change_note: "底图生成指令" });
      setPromptName("");
      await refresh();
    } catch (value) { setError(value instanceof Error ? value.message : "Prompt 创建失败"); }
    finally { setBusy(""); }
  }

  async function createRecipe(event: FormEvent) {
    event.preventDefault(); setBusy("create-recipe"); setError("");
    try {
      if (!recipeTemplates.length) throw new Error("请至少选择一个适用模板");
      await api.createRecipe({ name: recipeName, prompt_version_id: recipePrompt, model: activeModel, model_params: { quality: newRecipeQuality, reference_strategy: newRecipeReferenceStrategy, max_auto_regenerations: Number(newRecipeAutoRepair) }, template_ids: recipeTemplates, qa_policy: "commerce-basic-v1", candidate_count: recipeCandidates });
      setRecipeName("");
      await refresh();
    } catch (value) { setError(value instanceof Error ? value.message : "配方创建失败"); }
    finally { setBusy(""); }
  }

  async function publishRecipe(id: string) { setBusy(`publish-recipe-${id}`); setError(""); try { await api.publishRecipe(id); await refresh(); } catch (value) { setError(value instanceof Error ? value.message : "配方发布失败"); } finally { setBusy(""); } }
  async function publishPrompt(id: string) { setBusy(`publish-prompt-${id}`); setError(""); try { await api.publishPrompt(id); await refresh(); } catch (value) { setError(value instanceof Error ? value.message : "Prompt 发布失败"); } finally { setBusy(""); } }

  return <div className="catalog-stack">
    {busy && <OperationFeedback label="正在保存生产配置" detail="完成后页面会自动刷新。" compact />}
    {error && <div className="notice error">{error}</div>}

    <section className="panel recipe-explainer">
      <div className="panel-heading"><h3>一张图是怎么生成的</h3><p>Prompt 不负责最终排字，它只生成有场景、有光影并按模板留白的视觉底图。</p></div>
      <div className="recipe-flow"><article><b>1</b><strong>页面模板</strong><span>画布尺寸、文字区、商品区</span></article><i>＋</i><article><b>2</b><strong>底图 Prompt</strong><span>只控制场景、光影与留白</span></article><i>＋</i><article><b>3</b><strong>商品层</strong><span>原样合成参考商品，避免模型重绘</span></article><i>＋</i><article><b>4</b><strong>生成配方</strong><span>策略、质量、候选数、质检</span></article><i>→</i><article className="result"><b>5</b><strong>文字层</strong><span>把准确标题和正文排入留白区</span></article></div>
    </section>

    <div className="catalog-layout template-catalog-layout">
      <section className="panel">
        <div className="panel-heading"><h3>页面模板</h3><p>模板是尺寸与布局的唯一来源；预览比例与实际生成画布一致。</p></div>
        <div className="template-grid">{templates.map((template) => <article key={template.id}><TemplatePreview item={{ id: template.id, order: 1, page_type: (template.page_types[0] ?? "hero") as PageItem["page_type"], title: template.name, body: "后期排版的标题与正文", visual_goal: "", template_id: template.id, status: "draft" }} template={template} /><p><strong>{template.size}</strong> · {template.page_types.map(pageTypeLabel).join(" / ")} · {template.is_builtin ? "系统模板" : "自定义模板"}</p></article>)}</div>
      </section>
      <form className="panel catalog-side-form" onSubmit={createTemplate}>
        <div className="panel-heading"><h3>新建模板</h3><p>选择布局骨架和尺寸，系统会同步生图留白与后期文字坐标。</p></div>
        <div className="catalog-form">
          <Field label="模板名称"><input required disabled={!!busy} value={templateName} onChange={(event) => setTemplateName(event.target.value)} placeholder="例如：竖版生活场景" /></Field>
          <Field label="布局骨架"><select required disabled={!!busy} value={templateBase} onChange={(event) => setTemplateBase(event.target.value)}>{templates.filter((item) => item.is_builtin).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></Field>
          <Field label="适用页面"><select value={templatePageType} onChange={(event) => setTemplatePageType(event.target.value as PageItem["page_type"])}><option value="hero">主视觉</option><option value="selling_point">核心卖点</option><option value="function">功能说明</option><option value="scene">生活场景</option><option value="parameters">商品参数</option></select></Field>
          <Field label="生成尺寸"><select value={templateSize} onChange={(event) => setTemplateSize(event.target.value)}>{capabilities?.size_presets.map((item) => <option key={item.value} value={item.value}>{item.label} · {item.value}{item.experimental ? "（实验性）" : ""}</option>)}<option value="custom">自定义尺寸</option></select></Field>
          {templateSize === "custom" && <div className="dimension-fields"><Field label="宽度"><input type="number" min={16} max={3840} step={16} value={customWidth} onChange={(event) => setCustomWidth(event.target.value)} /></Field><span>×</span><Field label="高度"><input type="number" min={16} max={3840} step={16} value={customHeight} onChange={(event) => setCustomHeight(event.target.value)} /></Field></div>}
          <small className="form-help">最大正方形：{capabilities?.custom_size.max_square ?? "2880x2880"}；自定义宽高必须是 16 的倍数。</small>
          <button className="secondary" disabled={!!busy}>{busy === "create-template" ? "保存中…" : "保存模板"}</button>
        </div>
      </form>
    </div>

    <div className="catalog-layout recipe-catalog-layout">
      <section className="panel recipe-panel">
        <div className="panel-heading"><h3>生成配方</h3><p>把底图 Prompt、模型参数、模板范围和质检策略固定为可复用方案。</p></div>
        <div className="recipe-list">{recipes.map((recipe) => {
          const prompt = prompts.find((item) => item.id === recipe.prompt_version_id);
          return <article className={`recipe-card ${recipe.id === "commerce-lifestyle-demo-v1" ? "featured" : ""}`} key={recipe.id}><div className="recipe-card-head"><StatusBadge status={recipe.status} />{recipe.id === "commerce-lifestyle-demo-v1" && <span className="demo-tag">推荐演示</span>}</div><h3>{recipe.name}</h3><p>{prompt?.name ?? recipe.prompt_version_id}</p><div className="recipe-meta"><span>默认质量 {qualityLabel(recipeQuality(recipe))}</span><span>{referenceStrategyLabel(recipe)}</span><span>{Number(recipe.model_params.max_auto_regenerations ?? 0) > 0 ? "自动修复最多 1 次" : "单次生成"}</span><span>每页 {recipe.candidate_count} 个候选</span><span>{recipe.template_ids.length} 个模板</span></div><small>{recipe.model} · {recipe.qa_policy}</small>{recipe.status === "draft" && <button className="secondary" disabled={!!busy} onClick={() => void publishRecipe(recipe.id)}>{busy === `publish-recipe-${recipe.id}` ? "发布中…" : "发布配方"}</button>}</article>;
        })}</div>
      </section>
      <form className="panel catalog-side-form" onSubmit={createRecipe}>
        <div className="panel-heading"><h3>配置新配方</h3><p>质量是默认值，实际生产时仍可临时覆盖。</p></div>
        <div className="catalog-form">
          <Field label="配方名称"><input required disabled={!!busy} value={recipeName} onChange={(event) => setRecipeName(event.target.value)} placeholder="例如：洗衣机场景图配方" /></Field>
          <Field label="底图 Prompt"><select required disabled={!!busy} value={recipePrompt} onChange={(event) => setRecipePrompt(event.target.value)}>{publishedPrompts.map((item) => <option key={item.id} value={item.id}>{item.name} V{item.version}</option>)}</select></Field>
          <div className="form-grid compact"><Field label="默认质量"><select value={newRecipeQuality} onChange={(event) => setNewRecipeQuality(event.target.value)}><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option></select></Field><Field label="每页候选"><select value={recipeCandidates} onChange={(event) => setRecipeCandidates(Number(event.target.value))}><option value={1}>1 张</option><option value={2}>2 张</option><option value={3}>3 张</option></select></Field></div>
          <Field label="参考商品处理"><select value={newRecipeReferenceStrategy} onChange={(event) => setNewRecipeReferenceStrategy(event.target.value)}><option value="layered_product">原样商品层（推荐，避免重绘）</option><option value="model_edit">模型参考图编辑（适合融合创意）</option></select></Field>
          <Field label="自动图片修复"><select value={newRecipeAutoRepair} onChange={(event) => setNewRecipeAutoRepair(event.target.value)}><option value="0">关闭（每候选只调用一次生图）</option><option value="1">最多自动重生 1 次</option></select></Field>
          <small className="form-help">原样商品层：模型只生成空场景，系统把参考商品抠出后合成；模型编辑：参考图直接发送给生图模型，融合更自然但商品细节可能变化。</small>
          <fieldset className="template-checks"><legend>适用模板</legend>{templates.map((template) => <label key={template.id}><input type="checkbox" checked={recipeTemplates.includes(template.id)} onChange={(event) => setRecipeTemplates((current) => event.target.checked ? [...current, template.id] : current.filter((id) => id !== template.id))} /><span>{template.name}<small>{template.size}</small></span></label>)}</fieldset>
          <button className="primary" disabled={!!busy}>{busy === "create-recipe" ? "保存中…" : "保存配方草稿"}</button>
        </div>
      </form>
    </div>

    <section className="panel prompt-panel">
      <div className="panel-heading"><h3>底图生成指令（Prompt）</h3><p>这里只描述模型需要生成的视觉内容；真实标题、正文和字号不进入生图 Prompt。</p></div>
      <div className="prompt-runtime-preview"><div><span>选择模板查看运行时合并结果</span><select value={previewTemplateId} onChange={(event) => setPreviewTemplateId(event.target.value)}>{templates.map((template) => <option key={template.id} value={template.id}>{template.name} · {template.size}</option>)}</select></div><pre>{compilePromptPreview(selectedPrompt?.body ?? "", previewTemplate)}</pre></div>
      <div className="prompt-layout"><div className="prompt-list">{prompts.map((prompt) => <article key={prompt.id}><div><StatusBadge status={prompt.status} /><strong>{prompt.name} · V{prompt.version}</strong></div><p>{prompt.body}</p><small>{prompt.variables.map((item) => `{{${item}}}`).join(" · ") || "无变量"}</small>{prompt.status === "draft" && <button className="secondary" disabled={!!busy} onClick={() => void publishPrompt(prompt.id)}>{busy === `publish-prompt-${prompt.id}` ? "发布中…" : "发布此版本"}</button>}</article>)}</div><form className="catalog-form" onSubmit={createPrompt}><h4>新建底图 Prompt</h4><input required disabled={!!busy} value={promptName} onChange={(event) => setPromptName(event.target.value)} placeholder="Prompt 名称" /><textarea required disabled={!!busy} rows={11} value={promptBody} onChange={(event) => setPromptBody(event.target.value)} /><small className="form-help">推荐包含 {"{{visual_goal}}"}、{"{{scene_prompt_hint}}"} 和 {"{{composition_instruction}}"}。</small><button className="primary" disabled={!!busy}>{busy === "create-prompt" ? "保存中…" : "保存为草稿"}</button></form></div>
    </section>
  </div>;
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
function FormActions({ onClose, saving, label }: { onClose: () => void; saving: boolean; label: string }) { return <><div className="form-actions"><button type="button" className="secondary" disabled={saving} onClick={onClose}>取消</button><button className="primary" disabled={saving}>{saving ? "正在保存…" : label}</button></div>{saving && <OperationFeedback label={`正在${label}`} detail="数据正在提交，请勿关闭窗口。" compact />}</>; }
function OperationFeedback({ label, detail = "", compact = false }: { label: string; detail?: string; compact?: boolean }) { return <div className={`operation-feedback ${compact ? "compact" : ""}`} role="status" aria-live="polite"><span className="spinner" aria-hidden="true" /><div><strong>{label}</strong>{detail && <small>{detail}</small>}</div></div>; }
function StatusBadge({ status }: { status: string }) { return <span className={`badge badge-${status}`}>{statusLabel(status)}</span>; }
function projectOperationLabel(value: string) { return ({ generate: "正在生成内容规划", save: "正在保存规划草稿", confirm: "正在确认页面规划" } as Record<string, string>)[value] ?? "正在处理"; }
function productionActionLabel(value: string) { if (!value) return ""; if (value.startsWith("recompose-")) return "正在重新排版并质检"; if (value.startsWith("regenerate-")) return "正在提交单页重生成"; return ({ start: "正在提交生产任务", regenerate: "正在提交整套重新生产", export: "正在打包正式结果", recipe: "正在沉淀配方" } as Record<string, string>)[value] ?? "正在处理生产操作"; }
function batchOperationLabel(value: string) { return ({ start: "正在提交批量生产", retry: "正在提交失败项重试", pause: "正在暂停批次", resume: "正在恢复批次", export: "正在打包批量结果" } as Record<string, string>)[value] ?? "正在处理批次操作"; }
function statusLabel(status: string) { return ({ draft: "草稿", ready: "待执行", queued: "排队中", running: "执行中", planned: "已策划", producing: "生产中", reviewing: "审核中", review: "需确认", pass: "通过", needs_review: "待审核", approved: "已确认", rejected: "不采用", completed: "已完成", partial_failed: "部分失败", paused: "已暂停", failed: "失败", archived: "已归档", published: "已发布", testing: "测试中", deprecated: "已停用", pending: "待处理" } as Record<string, string>)[status] ?? status; }
function formatDate(value: string) { return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(value)); }
function formatBytes(value: number) { return value < 1024 * 1024 ? `${Math.max(1, Math.round(value / 1024))} KB` : `${(value / 1024 / 1024).toFixed(1)} MB`; }
function tabTitle(tab: Tab) { return tab === "projects" ? "商品项目" : tab === "batches" ? "多 SKU 批量任务" : "模板与配方"; }
function pageTypeLabel(value: string) { return ({ hero: "主视觉", selling_point: "核心卖点", function: "功能说明", scene: "生活场景", parameters: "商品参数" } as Record<string, string>)[value] ?? value; }
function usageLabel(value: Asset["usage"]) { return ({ product: "商品外观", detail: "局部细节", brand: "品牌风格", scene: "场景参考" } as Record<Asset["usage"], string>)[value]; }
function regionStyle(box: readonly number[]): CSSProperties {
  const [left = 0, top = 0, right = 1, bottom = 1] = box;
  return { position: "absolute", left: `${left * 100}%`, top: `${top * 100}%`, width: `${(right - left) * 100}%`, height: `${(bottom - top) * 100}%` };
}
function recipeQuality(recipe?: Recipe) {
  const quality = String(recipe?.model_params.quality ?? "high").toLowerCase();
  return ["low", "medium", "high"].includes(quality) ? quality : "high";
}
function qualityLabel(value: string) { return ({ low: "Low（快速）", medium: "Medium（均衡）", high: "High（精细）" } as Record<string, string>)[value] ?? value; }
function referenceStrategyLabel(recipe: Recipe) { return recipe.model_params.reference_strategy === "layered_product" ? "原样商品层" : "模型参考编辑"; }
function preflightComponentLabel(value: string) { return ({ image_generation: "图片生成", vision_ocr: "OCR", llm_review: "LLM 审查" } as Record<string, string>)[value] ?? value; }
function compilePromptPreview(body: string, template?: TemplateDefinition) {
  const values: Record<string, string> = {
    product_name: "示例商品",
    category: "商品品类",
    page_type: "生活场景",
    visual_goal: "呈现真实高端居住空间中的使用氛围与产品质感",
    scene_prompt_hint: template?.scene_prompt_hint ?? "生成有空间深度、自然光、材质和克制陈设的完整生活场景",
    composition_instruction: template?.composition_instruction ?? "在上方保留干净、低细节的文字安全区，商品主体不得进入该区域",
  };
  const compiled = body.replace(/{{(\w+)}}/g, (_, key: string) => values[key] ?? `[${key}]`);
  return `${compiled}\n\n[系统运行时追加]\n${values.composition_instruction}。仅生成视觉底图，不生成标题、正文、标语、参数或装饰性字符。商品本体自带的真实铭牌和控制面板除外。`;
}

export default App;
