import { FormEvent, ReactNode, useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import {
  api,
  Asset,
  Batch,
  LayoutLibrary,
  PageItem,
  PagePlan,
  PlanningRun,
  ProductionSnapshot,
  PromptVersion,
  ProductProfile,
  Project,
  Recipe,
  SystemPreflight,
  TemplateDefinition,
} from "./api";
import { StitchComposer, TypographyEditor } from "./production-tools";
import { LayoutCenter } from "./layout-center";
import { PlanningRunProgress, PlanningSuggestionPanel } from "./planning-assistant";
import { CandidateEditPanel, CandidateHistory } from "./candidate-editor";
import { Icon, IconButton, IconName } from "./ui";
import { statusLabel, statusTone } from "./status";

type Tab = "projects" | "batches" | "layouts" | "generation";
type Role = "business" | "admin";
type ProjectTab = "profile" | "planning" | "production" | "review" | "delivery";

const PROJECT_TABS: Array<{ key: ProjectTab; label: string; icon: IconName }> = [
  { key: "profile", label: "商品资料", icon: "profile" },
  { key: "planning", label: "内容规划", icon: "plan" },
  { key: "production", label: "图片生产", icon: "image" },
  { key: "review", label: "质检审核", icon: "review" },
  { key: "delivery", label: "交付导出", icon: "export" },
];

const isTab = (value: string | null): value is Tab => ["projects", "batches", "layouts", "generation"].includes(value ?? "");
const isProjectTab = (value: string | null): value is ProjectTab => PROJECT_TABS.some((item) => item.key === value);
const locationParams = () => new URLSearchParams(window.location.hash.replace(/^#/, ""));
function updateLocation(patch: Record<string, string | null>) {
  const params = locationParams();
  Object.entries(patch).forEach(([key, value]) => value ? params.set(key, value) : params.delete(key));
  const hash = params.toString();
  window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}${hash ? `#${hash}` : ""}`);
}

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
  const [tab, setTab] = useState<Tab>(() => {
    const value = locationParams().get("section");
    return isTab(value) ? value : "projects";
  });
  const [projects, setProjects] = useState<Project[]>([]);
  const [batches, setBatches] = useState<Batch[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showProjectForm, setShowProjectForm] = useState(false);
  const [showBatchForm, setShowBatchForm] = useState(false);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(() => locationParams().get("project"));
  const [role, setRole] = useState<Role>("admin");
  const [preflight, setPreflight] = useState<SystemPreflight | null>(null);
  const [navCollapsed, setNavCollapsed] = useState(() => window.localStorage.getItem("pcp-nav-collapsed") === "true");
  const [taskCenterOpen, setTaskCenterOpen] = useState(false);

  useEffect(() => {
    const syncLocation = () => {
      const params = locationParams();
      const nextSection = params.get("section");
      setTab(isTab(nextSection) ? nextSection : "projects");
      setSelectedProjectId(params.get("project"));
    };
    window.addEventListener("hashchange", syncLocation);
    window.addEventListener("popstate", syncLocation);
    return () => { window.removeEventListener("hashchange", syncLocation); window.removeEventListener("popstate", syncLocation); };
  }, []);

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
  const visibleProjectCount = useMemo(
    () => projects.filter((project) => project.status !== "archived").length,
    [projects],
  );
  const batchSkuCount = useMemo(
    () => batches.reduce((total, batch) => total + (batch.progress.total ?? batch.items.length), 0),
    [batches],
  );
  const taskItems = useMemo(() => [
    ...projects.filter((project) => ["producing", "reviewing"].includes(project.status)).map((project) => ({ id: project.id, title: project.name, detail: project.status === "producing" ? "图片生产正在进行" : "有候选图等待审核", status: project.status, projectId: project.id })),
    ...batches.filter((batch) => ["running", "paused", "partial_failed"].includes(batch.status)).map((batch) => ({ id: batch.id, title: batch.name, detail: `${batch.progress.completed ?? 0}/${batch.progress.total ?? batch.items.length} 个 SKU 已完成`, status: batch.status, projectId: "" })),
  ], [batches, projects]);
  const openProject = (id: string) => {
    setSelectedProjectId(id);
    updateLocation({ section: "projects", project: id, tab: "profile" });
  };
  const openSection = (next: Tab) => {
    setTab(next);
    setSelectedProjectId(null);
    updateLocation({ section: next, project: null, tab: null });
  };

  return (
    <div className={`app-shell ${navCollapsed ? "nav-collapsed" : ""}`}>
      <a className="skip-link" href="#main-content">跳到主要内容</a>
      <Sidebar collapsed={navCollapsed} onToggle={() => setNavCollapsed((current) => { const next = !current; window.localStorage.setItem("pcp-nav-collapsed", String(next)); return next; })} tab={tab} role={role} preflight={preflight} setRole={(next) => { setRole(next); if (next === "business" && ["layouts", "generation"].includes(tab)) openSection("projects"); else { setSelectedProjectId(null); updateLocation({ project: null, tab: null }); } }} setTab={openSection} />
      {selectedProjectId ? (
        <ProjectWorkspace
          projectId={selectedProjectId}
          onBack={() => { setSelectedProjectId(null); updateLocation({ project: null, tab: null }); }}
          onChanged={refresh}
        />
      ) : (
        <main id="main-content">
          <header className="topbar">
            <div><p className="page-context">内容生产平台</p><h2>{tabTitle(tab)}</h2></div>
            <div className="topbar-actions"><button className={`task-center-trigger ${taskItems.length ? "has-tasks" : ""}`} aria-expanded={taskCenterOpen} onClick={() => setTaskCenterOpen((current) => !current)}><Icon name="clock"/><span>任务</span>{taskItems.length > 0 && <b>{taskItems.length}</b>}</button>{(tab === "projects" || tab === "batches") && (
              <button className="primary" onClick={() => tab === "projects" ? setShowProjectForm(true) : setShowBatchForm(true)}>
                <Icon name="plus" />{tab === "projects" ? "创建项目" : "创建批次"}
              </button>
            )}</div>
          </header>
          {taskCenterOpen && (
            <TaskCenter
              items={taskItems}
              onClose={() => setTaskCenterOpen(false)}
              onOpenProject={(id) => { openProject(id); setTaskCenterOpen(false); }}
            />
          )}

          {(tab === "projects" || tab === "batches") && <section className="metrics">
            <Metric label="项目总数" value={visibleProjectCount} hint="不含已归档" />
            <Metric label="进行中" value={activeCount} hint="待策划或生产" />
            <Metric label="批量任务" value={batches.length} hint={`${batchSkuCount} 个 SKU`} />
            <Metric label="当前阶段" value="策划与模板" hint="素材、导入、规划" text />
          </section>}

          {error && <div className="notice error">{error}</div>}
          {loading ? <OperationFeedback label="正在连接本地服务" detail="正在读取项目与批次数据，请稍候。" /> : (
            tab === "projects" ? <ProjectTable projects={projects} onOpen={openProject} onRefresh={refresh} /> :
            tab === "batches" ? <BatchTable batches={batches} onOpenProject={openProject} onRefresh={refresh} /> :
            tab === "layouts" ? <LayoutCenter /> : <CatalogPanel />
          )}
        </main>
      )}

      {showProjectForm && <ProjectForm onClose={() => setShowProjectForm(false)} onCreated={async (projectId) => { setShowProjectForm(false); await refresh(); if (projectId) openProject(projectId); }} />}
      {showBatchForm && <BatchForm onClose={() => setShowBatchForm(false)} onCreated={async () => { setShowBatchForm(false); await refresh(); }} />}
    </div>
  );
}

function Sidebar({ tab, role, preflight, collapsed, onToggle, setRole, setTab }: { tab: Tab; role: Role; preflight: SystemPreflight | null; collapsed: boolean; onToggle: () => void; setRole: (role: Role) => void; setTab: (tab: Tab) => void }) {
  const items: Array<{ key: Tab; label: string; icon: IconName; admin?: boolean }> = [
    { key: "projects", label: "项目", icon: "projects" }, { key: "batches", label: "批量任务", icon: "batch" },
    { key: "layouts", label: "版式中心", icon: "layout", admin: true }, { key: "generation", label: "生成配置", icon: "settings", admin: true },
  ];
  return <aside className="sidebar" aria-label="全局导航">
    <div className="brand"><div className="brand-mark"><img src="/brand/content-studio-mark.png" alt="" /></div><div className="brand-copy"><strong>内容工场</strong><span>Content Studio</span></div></div>
    <nav>
      {items.filter((item) => !item.admin || role === "admin").map((item) => <button key={item.key} aria-label={item.label} aria-current={tab === item.key ? "page" : undefined} title={collapsed ? item.label : undefined} className={tab === item.key ? "active" : ""} onClick={() => setTab(item.key)}><Icon name={item.icon} /><span>{item.label}</span></button>)}
    </nav>
    <div className="role-switch"><span>当前角色</span><select value={role} onChange={(event) => setRole(event.target.value as Role)}><option value="business">业务用户</option><option value="admin">管理员 / 专家</option></select></div>
    <SystemStatus preflight={preflight} />
    <IconButton className="nav-collapse" icon="back" label={collapsed ? "展开导航" : "收起导航"} onClick={onToggle} />
  </aside>;
}

function TaskCenter({ items, onClose, onOpenProject }: { items: Array<{ id: string; title: string; detail: string; status: string; projectId: string }>; onClose: () => void; onOpenProject: (id: string) => void }) {
  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);
  return <aside className="task-center" aria-label="后台任务中心"><header><div><h3>后台任务</h3><p>离开原页面后任务仍会继续。</p></div><IconButton icon="close" label="关闭任务中心" onClick={onClose}/></header>{items.length ? <div>{items.map((item) => <button key={item.id} disabled={!item.projectId} onClick={() => item.projectId && onOpenProject(item.projectId)}><StatusBadge status={item.status}/><span><strong>{item.title}</strong><small>{item.detail}</small></span><Icon name="chevron-down"/></button>)}</div> : <div className="task-center-empty"><Icon name="check"/><strong>当前没有运行中的任务</strong><p>生成、导出和批量任务会显示在这里。</p></div>}</aside>;
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
  const [activeTab, setActiveTab] = useState<ProjectTab>(() => {
    const locationTab = locationParams().get("tab");
    if (isProjectTab(locationTab)) return locationTab;
    const stored = window.sessionStorage.getItem(`project-tab:${projectId}`);
    return isProjectTab(stored) ? stored : "profile";
  });
  const [project, setProject] = useState<Project | null>(null);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [plan, setPlan] = useState<PagePlan | null>(null);
  const [layoutLibraries, setLayoutLibraries] = useState<LayoutLibrary[]>([]);
  const [draftLibraryId, setDraftLibraryId] = useState("library-square-2048");
  const [templates, setTemplates] = useState<TemplateDefinition[]>([]);
  const [recipes, setRecipes] = useState<Recipe[]>([]);
  const [production, setProduction] = useState<ProductionSnapshot | null>(null);
  const [planningRun, setPlanningRun] = useState<PlanningRun | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [editingProfile, setEditingProfile] = useState(false);
  const [selectedPlanPageId, setSelectedPlanPageId] = useState("");
  const productionJobs = production?.pages.flatMap((row) => row.job ? [row.job] : []) ?? [];
  const hasActiveProduction = productionJobs.some((job) => ["queued", "running"].includes(job.status));
  const hasActivePlanning = planningRun ? ["queued", "running"].includes(planningRun.status) : false;
  const workspaceStatus = hasActiveProduction
    ? "producing"
    : productionJobs.length > 0 && productionJobs.every((job) => job.status === "failed")
      ? "failed"
      : project?.status ?? "draft";
  const activeLibraryId = plan?.layout_library_id ?? draftLibraryId;
  const activeLibrary = layoutLibraries.find((item) => item.id === activeLibraryId);
  const availableTemplates = templates.filter((item) => item.library_id === activeLibraryId);
  const planningProductAsset = assets.find((asset) => asset.mime_type.startsWith("image/") && asset.usage === "product");
  const planningProductImageUrl = planningProductAsset ? api.assetUrl(planningProductAsset.id) : "/demo-product-reference.jpg";
  const reviewCount = production?.pages.filter((row) => row.candidates.some((candidate) => candidate.qa?.status !== "pass") || !row.decision).length ?? 0;
  const approvedCount = production?.pages.filter((row) => row.decision?.decision === "approved").length ?? 0;

  const selectTab = (next: ProjectTab) => {
    setActiveTab(next);
    window.sessionStorage.setItem(`project-tab:${projectId}`, next);
    updateLocation({ section: "projects", project: projectId, tab: next });
  };

  useEffect(() => {
    if (!plan?.items.length) { setSelectedPlanPageId(""); return; }
    if (!plan.items.some((item) => item.id === selectedPlanPageId)) setSelectedPlanPageId(plan.items[0].id);
  }, [plan, selectedPlanPageId]);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [projectRow, assetRows, planRow, templateRows, recipeRows, libraryRows, planningRuns] = await Promise.all([
        api.getProject(projectId), api.listAssets(projectId), api.getPlan(projectId), api.listTemplates(), api.listRecipes(), api.listLayoutLibraries(), api.listPlanningRuns(projectId),
      ]);
      setProject(projectRow); setAssets(assetRows); setPlan(planRow); setTemplates(templateRows); setRecipes(recipeRows); setLayoutLibraries(libraryRows);
      setDraftLibraryId(planRow?.layout_library_id ?? libraryRows.find((item) => item.id === "library-square-2048")?.id ?? libraryRows[0]?.id ?? "library-square-2048");
      setPlanningRun(planningRuns.find((item) => ["queued", "running", "failed"].includes(item.status) || (item.status === "completed" && item.applied_plan_version === 0)) ?? null);
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

  useEffect(() => {
    if (!hasActivePlanning || !planningRun) return;
    const timer = window.setTimeout(() => {
      void api.getPlanningRun(projectId, planningRun.id).then(setPlanningRun).catch((reason) => setError(reason instanceof Error ? reason.message : "规划进度刷新失败"));
    }, 900);
    return () => window.clearTimeout(timer);
  }, [hasActivePlanning, planningRun?.id, planningRun?.status, projectId]);

  async function generatePlan() {
    setBusy("generate"); setError(""); setMessage("");
    try {
      const run = await api.startPlanningRun(projectId, draftLibraryId);
      setPlanningRun(run);
      setMessage("AI 内容规划已提交；完成后可按页或按字段采用，不会直接覆盖当前草稿。");
    }
    catch (reason) { setError(reason instanceof Error ? reason.message : "生成失败"); }
    finally { setBusy(""); }
  }

  async function applyPlanningSuggestion(selectedFields: Record<string, string[]>) {
    if (!planningRun) return;
    setBusy("apply-planning"); setError(""); setMessage("");
    try {
      const nextPlan = await api.applyPlanningRun(projectId, planningRun.id, selectedFields);
      const [projectRow] = await Promise.all([api.getProject(projectId), onChanged()]);
      setPlan(nextPlan); setProject(projectRow); setProduction(null); setPlanningRun(null);
      setMessage("所选 AI 建议已应用为新的规划草稿；你可以继续人工修改，再保存或确认规划。");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "应用规划建议失败"); }
    finally { setBusy(""); }
  }

  async function dismissPlanningSuggestion() {
    if (!planningRun) return;
    try { await api.dismissPlanningRun(projectId, planningRun.id); setPlanningRun(null); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "忽略规划建议失败"); }
  }

  async function savePlan(confirmed: boolean) {
    if (!plan) return;
    setBusy(confirmed ? "confirm" : "save"); setError(""); setMessage("");
    try {
      const saved = await api.savePlan(projectId, { items: plan.items, layout_library_id: plan.layout_library_id, confirmed });
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

  function reorderPage(index: number, target: number) {
    if (!plan || index === target || index < 0 || target < 0 || index >= plan.items.length || target >= plan.items.length) return;
    const items = [...plan.items];
    const [moved] = items.splice(index, 1);
    items.splice(target, 0, moved);
    setPlan({ ...plan, confirmed: false, items: items.map((item, itemIndex) => ({ ...item, order: itemIndex + 1, status: "draft" })) });
  }

  function deletePage(index: number) {
    if (!plan || plan.items.length <= 1) return;
    setPlan({ ...plan, confirmed: false, items: plan.items.filter((_, itemIndex) => itemIndex !== index).map((item, itemIndex) => ({ ...item, order: itemIndex + 1, status: "draft" })) });
  }

  function addPage() {
    if (!plan) return;
    const template = availableTemplates.find((item) => item.page_types.includes("selling_point")) ?? availableTemplates[0];
    setPlan({ ...plan, confirmed: false, items: [...plan.items, { id: crypto.randomUUID(), order: plan.items.length + 1, page_type: "selling_point", title: "新页面标题", body: "请填写页面文案", visual_goal: "请填写视觉目标", template_id: template?.id ?? "split-left", feature_points: [], heading_level: 2, status: "draft" }] });
  }

  function selectLayoutLibrary(libraryId: string) {
    setDraftLibraryId(libraryId);
    if (!plan || libraryId === plan.layout_library_id) return;
    const nextTemplates = templates.filter((item) => item.library_id === libraryId);
    if (!nextTemplates.length) {
      setError("所选版式库还没有已发布模板，请先在版式中心发布模板");
      return;
    }
    const remappedItems = plan.items.map((item) => {
      const nextTemplate = nextTemplates.find((template) => template.page_types.includes(item.page_type)) ?? nextTemplates[0];
      return { ...item, template_id: nextTemplate.id, status: "draft" as const };
    });
    setPlan({ ...plan, layout_library_id: libraryId, confirmed: false, items: remappedItems });
    setProduction(null);
    setError("");
    setMessage("已切换版式库并按页面类型重新匹配模板；请检查横竖版构图后重新确认规划");
  }

  if (loading || !project) return <main id="main-content"><OperationFeedback label="正在加载项目工作台" detail="正在同步商品档案、内容规划和生产状态。" /></main>;
  return <main id="main-content" className={`project-workspace project-tab-${activeTab}`}>
    <header className="topbar workspace-topbar">
      <div><button className="back-button" onClick={onBack}><Icon name="back" /> 返回项目</button><div className="workspace-title"><h2>{project.name}</h2><IconButton label="编辑商品档案" icon="edit" onClick={() => setEditingProfile(true)} /></div><p className="workspace-meta">{project.profile.sku} · {project.profile.category}<span>已保存</span></p></div>
      <div className="workspace-header-actions"><StatusBadge status={workspaceStatus} />{activeTab === "production" && plan?.confirmed && <button className="primary" onClick={() => document.querySelector(".production-panel")?.scrollIntoView({ behavior: "smooth" })}>查看生产任务</button>}</div>
    </header>
    <nav className="project-tabs" role="tablist" aria-label="项目流程" onKeyDown={(event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const current = PROJECT_TABS.findIndex((item) => item.key === activeTab);
      const target = event.key === "Home" ? 0 : event.key === "End" ? PROJECT_TABS.length - 1 : (current + (event.key === "ArrowRight" ? 1 : -1) + PROJECT_TABS.length) % PROJECT_TABS.length;
      selectTab(PROJECT_TABS[target].key);
      (event.currentTarget.children[target] as HTMLElement | undefined)?.focus();
    }}>
      {PROJECT_TABS.map((item) => {
        const badge = item.key === "review" && reviewCount ? reviewCount : item.key === "delivery" && approvedCount ? approvedCount : 0;
        const complete = item.key === "profile" || (item.key === "planning" && !!plan) || (item.key === "production" && !!production?.pages.some((row) => row.candidates.length)) || (item.key === "review" && approvedCount > 0) || (item.key === "delivery" && !!production?.ready_for_export);
        return <button key={item.key} role="tab" aria-selected={activeTab === item.key} tabIndex={activeTab === item.key ? 0 : -1} className={`${activeTab === item.key ? "active" : ""} ${complete ? "complete" : ""}`} onClick={() => selectTab(item.key)}><Icon name={item.icon} /><span>{item.label}</span>{badge > 0 && <b>{badge}</b>}</button>;
      })}
    </nav>
    {error && <div className="notice error">{error}</div>}
    {message && <div className="notice success">{message}</div>}
    {busy && <OperationFeedback label={projectOperationLabel(busy)} detail="操作完成前请保持当前页面打开。" compact />}

    {activeTab === "profile" && <section className="workspace-grid profile-workspace">
      <article className="panel compact-panel">
        <div className="panel-heading editable-heading"><div><h3>商品档案</h3><p>数字、型号和参数作为已确认事实进入后续生成。</p></div><button className="ghost-button mini" onClick={() => setEditingProfile(true)}>编辑资料</button></div>
        <div className="profile-details">
          <Info label="商品名称" value={project.profile.name} /><Info label="SKU / 型号" value={`${project.profile.sku} / ${project.profile.model || "—"}`} />
          <Info label="品类" value={project.profile.category} /><Info label="核心卖点" value={project.profile.selling_points.join("、") || "暂未填写"} wide />
          <Info label="商品参数" value={Object.entries(project.profile.parameters).map(([key, value]) => `${key} ${value}`).join(" · ") || "暂未填写"} wide />
        </div>
      </article>
      <AssetPanel projectId={projectId} assets={assets} onUploaded={async () => { setAssets(await api.listAssets(projectId)); setProject(await api.getProject(projectId)); }} />
    </section>}

    {activeTab === "planning" && <section className="panel planning-panel">
      <div className="panel-heading planning-heading">
        <div><h3>多页内容规划</h3><p>{plan ? `版本 V${plan.version} · ${plan.confirmed ? "已确认" : "草稿"}` : "基于商品资料生成主视觉、卖点、功能、场景和参数页。"}</p></div>
        <div className="button-row">
          {plan && <button className="ghost-button" disabled={!!busy} onClick={addPage}>＋ 新增页面</button>}
          {plan && <><button className="secondary" disabled={!!busy} onClick={() => void savePlan(false)}>{busy === "save" ? "保存中…" : "保存草稿"}</button><button className="primary" disabled={!!busy} onClick={() => void savePlan(true)}>{busy === "confirm" ? "确认中…" : "确认规划"}</button></>}
          <button className={plan ? "ghost-button" : "primary"} disabled={!!busy || hasActivePlanning} onClick={() => void generatePlan()}>{busy === "generate" || hasActivePlanning ? "AI 规划中…" : plan ? "重新规划文案" : "AI 生成内容规划"}</button>
        </div>
      </div>
      {planningRun && ["queued", "running", "failed"].includes(planningRun.status) && <PlanningRunProgress run={planningRun} />}
      {planningRun?.status === "completed" && <PlanningSuggestionPanel run={planningRun} currentPlan={plan} applying={busy === "apply-planning"} onApply={applyPlanningSuggestion} onClose={() => void dismissPlanningSuggestion()} />}
      {!plan ? <div className="empty-state inline-empty"><strong>还没有内容规划</strong><p>录入商品卖点和参数后，可生成一套多页内容结构。</p><button className="primary" disabled={!!busy || hasActivePlanning} onClick={() => void generatePlan()}>{hasActivePlanning ? "规划中…" : "生成内容规划"}</button></div> : <PlanningWorkbench
        plan={plan}
        productImageUrl={planningProductImageUrl}
        selectedPageId={selectedPlanPageId}
        templates={availableTemplates}
        libraries={layoutLibraries}
        activeLibrary={activeLibrary}
        activeLibraryId={activeLibraryId}
        recipeCount={recipes.filter((item) => item.status === "published").length}
        disabled={!!busy}
        onSelectPage={setSelectedPlanPageId}
        onSelectLibrary={selectLayoutLibrary}
        onChangePage={(index, patch) => updatePage(index, patch)}
        onMovePage={movePage}
        onReorderPage={reorderPage}
        onDeletePage={deletePage}
      />}
    </section>}
    {activeTab === "production" && <>{plan && !plan.confirmed && <div className="production-gate" role="status"><span>下一步</span><div><strong>图片生产尚未开始</strong><p>当前是规划草稿。请先检查页面内容并点击“确认规划”。</p></div><button className="secondary" onClick={() => selectTab("planning")}>前往内容规划</button></div>}{!plan && <FlowEmptyState icon="plan" title="还没有内容规划" detail="先生成或手动创建页面结构，再开始图片生产。" action="前往内容规划" onAction={() => selectTab("planning")} />}{plan?.confirmed && <ProductionPanel mode="production" projectId={projectId} recipes={recipes} referenceAssets={assets.filter((item) => item.mime_type.startsWith("image/"))} snapshot={production} onRefresh={async () => { setProduction(await api.getProduction(projectId)); setProject(await api.getProject(projectId)); await onChanged(); }} />}</>}
    {activeTab === "review" && (production?.pages.some((row) => row.candidates.length) ? <ProductionPanel mode="review" projectId={projectId} recipes={recipes} referenceAssets={assets.filter((item) => item.mime_type.startsWith("image/"))} snapshot={production} onRefresh={async () => { setProduction(await api.getProduction(projectId)); setProject(await api.getProject(projectId)); await onChanged(); }} /> : <FlowEmptyState icon="review" title="还没有可审核的候选图" detail="完成图片生产后，候选图和 QA 问题会集中显示在这里。" action="前往图片生产" onAction={() => selectTab("production")} />)}
    {activeTab === "delivery" && (production?.pages.some((row) => row.candidates.length) ? <DeliveryWorkspace projectId={projectId} snapshot={production} /> : <FlowEmptyState icon="export" title="还没有可交付的图片" detail="至少完成一页图片生产后，才能编排顺序并导出。" action="前往图片生产" onAction={() => selectTab("production")} />)}
    {editingProfile && <ProfileEditor project={project} onClose={() => setEditingProfile(false)} onSaved={async () => { setEditingProfile(false); await load(); await onChanged(); setMessage("商品档案已更新，再次确认页面规划后可重新生产"); }} />}
  </main>;
}

function FlowEmptyState({ icon, title, detail, action, onAction }: { icon: IconName; title: string; detail: string; action: string; onAction: () => void }) {
  return <section className="flow-empty"><Icon name={icon} size={36} /><h3>{title}</h3><p>{detail}</p><button className="primary" onClick={onAction}>{action}</button></section>;
}

function DeliveryWorkspace({ projectId, snapshot }: { projectId: string; snapshot: ProductionSnapshot }) {
  const approved = snapshot.pages.filter((row) => row.decision?.decision === "approved").length;
  const [busy, setBusy] = useState(false);
  const [downloadUrl, setDownloadUrl] = useState("");
  const [error, setError] = useState("");
  const candidateCount = snapshot.pages.reduce((total, row) => total + row.candidates.length, 0);
  async function exportPackage() {
    setBusy(true); setError("");
    try { const result = await api.exportProject(projectId); setDownloadUrl(api.resolveUrl(result.download_url)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "导出失败"); }
    finally { setBusy(false); }
  }
  return <section className="delivery-workspace"><header className="section-heading"><div><h3>交付导出</h3><p>默认选择已通过页面，按原始分辨率拼接并导出。</p></div><div className="delivery-header-actions"><div className="delivery-summary"><strong>{approved}/{snapshot.pages.length}</strong><span>页面已通过</span></div><button className="primary" disabled={busy || approved === 0} onClick={() => void exportPackage()}><Icon name="download"/>{busy ? "正在打包…" : "导出交付包"}</button></div></header>{error && <div className="notice error">{error}</div>}{downloadUrl && <div className="notice success delivery-download"><strong>交付包已生成</strong><a href={downloadUrl}>下载 ZIP 文件</a></div>}{candidateCount > 1 ? <StitchComposer projectId={projectId} snapshot={snapshot} /> : <section className="single-delivery"><Icon name="image" size={30}/><div><strong>当前项目只有 1 张交付图片</strong><p>无需拼接；点击上方“导出交付包”即可下载原图、分层文件与质检记录。</p></div></section>}</section>;
}

function AssetPanel({ projectId, assets, onUploaded }: { projectId: string; assets: Asset[]; onUploaded: () => Promise<void> }) {
  const [file, setFile] = useState<File | null>(null);
  const [usage, setUsage] = useState<Asset["usage"]>("product");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [uploadedFileName, setUploadedFileName] = useState("");
  const [dragActive, setDragActive] = useState(false);
  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!file) return;
    const form = event.currentTarget;
    setBusy(true); setError(""); setUploadedFileName("");
    try {
      const uploaded = await api.uploadAsset(projectId, file, usage);
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
      <label className={`file-picker ${dragActive ? "drag-active" : ""}`} onDragEnter={(event) => { event.preventDefault(); setDragActive(true); }} onDragOver={(event) => event.preventDefault()} onDragLeave={() => setDragActive(false)} onDrop={(event) => { event.preventDefault(); setDragActive(false); setFile(event.dataTransfer.files?.[0] ?? null); setUploadedFileName(""); setError(""); }}><input type="file" accept=".png,.jpg,.jpeg,.webp,.pdf" onChange={(event) => { setFile(event.target.files?.[0] ?? null); setUploadedFileName(""); setError(""); }} /><span>{dragActive ? "松开以添加素材" : file?.name ?? "选择或拖入素材文件"}</span></label>
      <button className="secondary" disabled={!file || busy}>{busy ? "上传绑定中…" : "上传并绑定"}</button>
    </form>
    {busy && <OperationFeedback label="正在上传素材" detail="正在保存文件并绑定到当前项目，完成前请勿开始生产。" compact />}
    {file && !busy && <div className="notice warning asset-notice">已选择 <strong>{file.name}</strong>，但尚未上传；当前生产任务不会使用此文件。请点击“上传并绑定”。</div>}
    {uploadedFileName && <div className="notice success asset-notice"><strong>{uploadedFileName}</strong> 已上传并绑定到当前项目，可用于下一次生产。</div>}
    {error && <div className="notice error">{error}</div>}
    <div className="asset-list">{assets.length === 0 ? <p className="muted">尚未上传参考素材</p> : assets.map((asset) => <a key={asset.id} href={api.assetUrl(asset.id)} target="_blank" rel="noreferrer" className="asset-item">{asset.mime_type.startsWith("image/") ? <img src={api.assetUrl(asset.id)} alt="" /> : <span className="pdf-icon">PDF</span>}<div><strong>{asset.file_name}</strong><small>{usageLabel(asset.usage)} · {formatBytes(asset.size_bytes)}</small></div></a>)}</div>
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

function LayoutLibraryPicker({ libraries, selectedId, onSelect, disabled }: { libraries: LayoutLibrary[]; selectedId: string; onSelect: (id: string) => void; disabled: boolean }) {
  return <div className="project-library-picker">
    <div className="project-library-copy"><strong>选择本项目的版式库</strong><span>一个项目规划只使用同一画布尺寸，便于批量生成与后续长图拼接。</span></div>
    <div className="project-library-options">
      {libraries.map((library) => <button
        type="button"
        key={library.id}
        className={library.id === selectedId ? "selected" : ""}
        disabled={disabled}
        onClick={() => onSelect(library.id)}
      >
        <span className="library-ratio-icon"><i style={{ aspectRatio: `${library.width} / ${library.height}` }} /></span>
        <span><strong>{library.name}</strong><small>{library.size} · {library.template_count} 个模板</small></span>
        {library.id === selectedId && <b>当前</b>}
      </button>)}
    </div>
  </div>;
}

function PlanningWorkbench({ plan, productImageUrl, selectedPageId, templates, libraries, activeLibrary, activeLibraryId, recipeCount, disabled, onSelectPage, onSelectLibrary, onChangePage, onMovePage, onReorderPage, onDeletePage }: {
  plan: PagePlan;
  productImageUrl: string;
  selectedPageId: string;
  templates: TemplateDefinition[];
  libraries: LayoutLibrary[];
  activeLibrary?: LayoutLibrary;
  activeLibraryId: string;
  recipeCount: number;
  disabled: boolean;
  onSelectPage: (id: string) => void;
  onSelectLibrary: (id: string) => void;
  onChangePage: (index: number, patch: Partial<PageItem>) => void;
  onMovePage: (index: number, direction: -1 | 1) => void;
  onReorderPage: (index: number, target: number) => void;
  onDeletePage: (index: number) => void;
}) {
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const selectedIndex = Math.max(0, plan.items.findIndex((item) => item.id === selectedPageId));
  const selected = plan.items[selectedIndex] ?? plan.items[0];
  return <div className="planning-workbench">
    <aside className="planning-page-rail"><header><strong>内容页</strong><span>{plan.items.length}</span></header>{plan.items.map((item, index) => <div key={item.id} draggable={!disabled} className={`${selected?.id === item.id ? "active" : ""} ${dragIndex === index ? "dragging" : ""}`} onDragStart={() => setDragIndex(index)} onDragEnd={() => setDragIndex(null)} onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); if (dragIndex !== null) onReorderPage(dragIndex, index); setDragIndex(null); }}><button className="planning-page-select" onClick={() => onSelectPage(item.id)}><Icon name="grip"/><span className="page-number">{String(item.order).padStart(2, "0")}</span><span><strong>{item.title}</strong><small>{pageTypeLabel(item.page_type)} · H{item.heading_level}</small></span><StatusBadge status={item.status}/></button><span className="keyboard-sort"><button aria-label={`上移${item.title}`} disabled={index === 0 || disabled} onClick={() => onMovePage(index, -1)}>↑</button><button aria-label={`下移${item.title}`} disabled={index === plan.items.length - 1 || disabled} onClick={() => onMovePage(index, 1)}>↓</button></span></div>)}</aside>
    <div className="planning-page-canvas">{selected && <PageEditor item={selected} productImageUrl={productImageUrl} templates={templates} onChange={(patch) => onChangePage(selectedIndex, patch)} onMoveUp={() => onMovePage(selectedIndex, -1)} onMoveDown={() => onMovePage(selectedIndex, 1)} onDelete={() => onDeletePage(selectedIndex)} first={selectedIndex === 0} last={selectedIndex === plan.items.length - 1}/>}</div>
    <aside className="planning-inspector"><section><h4>页面设置</h4><p><span>页码</span><strong>{selectedIndex + 1}/{plan.items.length}</strong></p><p><span>规划版本</span><strong>V{plan.version}</strong></p><p><span>可用配方</span><strong>{recipeCount} 套</strong></p></section><section><h4>版式库</h4><label><span>当前规格</span><select value={activeLibraryId} disabled={disabled} onChange={(event) => onSelectLibrary(event.target.value)}>{libraries.map((library) => <option key={library.id} value={library.id}>{library.name}</option>)}</select></label><small>{activeLibrary?.size} · {activeLibrary?.template_count} 个模板</small></section><section><h4>流程提示</h4><div className={`planning-status ${plan.confirmed ? "success" : "warning"}`}><Icon name={plan.confirmed ? "check" : "info"}/><div><strong>{plan.confirmed ? "规划已确认" : "当前为草稿"}</strong><p>{plan.confirmed ? "可以前往图片生产；再次修改会恢复为草稿。" : "确认后才会开放图片生产。"}</p></div></div></section></aside>
  </div>;
}

function PageEditor({ item, productImageUrl, templates, onChange, onMoveUp, onMoveDown, onDelete, first, last }: { item: PageItem; productImageUrl: string; templates: TemplateDefinition[]; onChange: (patch: Partial<PageItem>) => void; onMoveUp: () => void; onMoveDown: () => void; onDelete: () => void; first: boolean; last: boolean }) {
  const template = templates.find((row) => row.id === item.template_id) ?? templates[0];
  const compatible = templates.filter((row) => row.page_types.includes(item.page_type));
  return <article className="page-editor">
    <TemplatePreview item={item} template={template} productImageUrl={productImageUrl} />
    <div className="page-fields">
      <div className="page-meta"><span>第 {item.order} 页 · {pageTypeLabel(item.page_type)}</span><div className="page-tools"><select aria-label="标题层级" value={item.heading_level} onChange={(event) => onChange({ heading_level: Number(event.target.value) as PageItem["heading_level"] })}><option value="1">H1</option><option value="2">H2</option><option value="3">H3</option><option value="4">H4</option><option value="5">H5</option></select><select value={item.page_type} onChange={(event) => { const pageType = event.target.value as PageItem["page_type"]; const nextTemplate = templates.find((row) => row.page_types.includes(pageType)); onChange({ page_type: pageType, template_id: nextTemplate?.id ?? item.template_id }); }}><option value="hero">主视觉</option><option value="selling_point">核心卖点</option><option value="function">功能说明</option><option value="scene">场景</option><option value="parameters">参数</option></select><select value={item.template_id} onChange={(event) => onChange({ template_id: event.target.value })}>{compatible.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}</select><button title="上移" disabled={first} onClick={onMoveUp}>↑</button><button title="下移" disabled={last} onClick={onMoveDown}>↓</button><button title="删除" disabled={first && last} onClick={onDelete}>×</button></div></div>
      <Field label="页面标题"><input value={item.title} onChange={(event) => onChange({ title: event.target.value })} /></Field>
      <Field label="正文文案"><textarea rows={2} value={item.body} onChange={(event) => onChange({ body: event.target.value })} /></Field>
      <Field label="视觉目标"><textarea rows={2} value={item.visual_goal} onChange={(event) => onChange({ visual_goal: event.target.value })} /></Field>
      {template?.feature_slots.length ? <div className="feature-point-editor">
        <header><span>图文卖点组</span><small>{item.feature_points.length}/{template.feature_slots[0].max_items} 项 · 图标独立生成，文字可继续编辑</small></header>
        {item.feature_points.map((point, index) => <article key={point.id}>
          <b>{String(index + 1).padStart(2, "0")}</b>
          <div>
            <input aria-label={`卖点 ${index + 1} 标题`} value={point.title} onChange={(event) => onChange({ feature_points: item.feature_points.map((row) => row.id === point.id ? { ...row, title: event.target.value } : row) })}/>
            <input aria-label={`卖点 ${index + 1} 说明`} value={point.description} onChange={(event) => onChange({ feature_points: item.feature_points.map((row) => row.id === point.id ? { ...row, description: event.target.value } : row) })}/>
            <input aria-label={`卖点 ${index + 1} 图标概念`} value={point.icon_concept} onChange={(event) => onChange({ feature_points: item.feature_points.map((row) => row.id === point.id ? { ...row, icon_concept: event.target.value } : row) })}/>
          </div>
          <button type="button" aria-label={`删除卖点 ${index + 1}`} onClick={() => onChange({ feature_points: item.feature_points.filter((row) => row.id !== point.id) })}>×</button>
        </article>)}
        <button type="button" className="ghost-button mini" disabled={item.feature_points.length >= template.feature_slots[0].max_items} onClick={() => onChange({ feature_points: [...item.feature_points, { id: `feature-${crypto.randomUUID()}`, title: "新卖点", description: "填写一句简短说明", icon_concept: "简洁线性图标，不含文字或数字", fact_refs: [] }] })}>＋ 新增卖点</button>
      </div> : null}
    </div>
  </article>;
}

function FittedPreviewText({ text, maxSize, weight = 400 }: { text: string; maxSize: number; weight?: number }) {
  const boxRef = useRef<HTMLDivElement>(null);
  const textRef = useRef<HTMLSpanElement>(null);
  useLayoutEffect(() => {
    const box = boxRef.current;
    const target = textRef.current;
    if (!box || !target) return;
    const fit = () => {
      let low = 5;
      let high = maxSize;
      let best = low;
      while (low <= high) {
        const size = Math.floor((low + high) / 2);
        target.style.fontSize = `${size}px`;
        if (target.scrollWidth <= box.clientWidth + 1 && target.scrollHeight <= box.clientHeight + 2) {
          best = size;
          low = size + 1;
        } else high = size - 1;
      }
      target.style.fontSize = `${best}px`;
    };
    fit();
    const observer = new ResizeObserver(fit);
    observer.observe(box);
    return () => observer.disconnect();
  }, [maxSize, text]);
  return <div ref={boxRef} className="preview-copy-fit"><span ref={textRef} style={{ fontWeight: weight }}>{text}</span></div>;
}

function TemplatePreview({ item, template, productImageUrl }: { item: PageItem; template?: TemplateDefinition; productImageUrl: string }) {
  const titleBox = template?.title_box ?? template?.text_box ?? [0.09, 0.07, 0.91, 0.18];
  const bodyBox = template?.body_box ?? template?.text_box ?? [0.09, 0.19, 0.91, 0.29];
  const productBox = template?.product_anchor_box ?? template?.product_box ?? [0.20, 0.32, 0.80, 0.94];
  const featureSlot = template?.feature_slots[0];
  return <div className={`template-preview ${template?.layout ?? "center"}`} style={{ aspectRatio: `${template?.width ?? 2048} / ${template?.height ?? 2048}` }}><div className="preview-environment"><i /><b /><em /></div><div className="preview-copy preview-title" style={regionStyle(titleBox)}><FittedPreviewText text={item.title} maxSize={18} weight={700}/></div><div className="preview-copy preview-body" style={regionStyle(bodyBox)}><FittedPreviewText text={item.body} maxSize={12}/></div>{featureSlot && <div className={`preview-feature-group ${featureSlot.icon_position}`} style={{ ...regionStyle(featureSlot.box), gridTemplateColumns: `repeat(${Math.min(featureSlot.columns, Math.max(1, item.feature_points.length))}, 1fr)` }}>{item.feature_points.map((point) => <span key={point.id}><i>◇</i><b>{point.title}</b><em>{point.description}</em></span>)}</div>}<div className="product-shape" style={regionStyle(productBox)}><img src={productImageUrl} alt="商品参考素材" /></div><small>{template?.size ?? "2048x2048"} · {template?.name ?? item.template_id}</small></div>;
}

function ProductionPanel({ projectId, recipes, referenceAssets, snapshot, mode = "production", onRefresh }: { projectId: string; recipes: Recipe[]; referenceAssets: Asset[]; snapshot: ProductionSnapshot | null; mode?: "production" | "review"; onRefresh: () => Promise<void> }) {
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [downloadUrl, setDownloadUrl] = useState("");
  const publishedRecipes = recipes.filter((item) => item.status === "published");
  const isGoldenDemo = snapshot?.project.profile.output_requirements.includes("黄金演示") ?? false;
  const recommendedRecipeId = isGoldenDemo ? "commerce-lifestyle-demo-v1" : publishedRecipes[0]?.id;
  const [recipeId, setRecipeId] = useState(recommendedRecipeId ?? "commerce-detail-v1");
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
  const overallProgress = pages.length
    ? Math.round(pages.reduce((total, row) => total + jobProgress(row.job), 0) / pages.length)
    : 0;
  const isProductionActive = activeJobs > 0;
  const canExport = snapshot?.ready_for_export ?? false;
  const immediateActionLabel = productionActionLabel(busy);
  const referenceUrls = referenceAssets
    .filter((asset) => asset.usage === "product" || asset.usage === "detail")
    .map((asset) => api.assetUrl(asset.id));
  const [selectedPageId, setSelectedPageId] = useState("");
  const [selectedCandidateId, setSelectedCandidateId] = useState("");
  useEffect(() => {
    if (!pages.length) return;
    if (!pages.some((row) => row.page.id === selectedPageId)) setSelectedPageId(pages.find((row) => row.candidates.length)?.page.id ?? pages[0].page.id);
  }, [pages, selectedPageId]);
  const selectedPage = pages.find((row) => row.page.id === selectedPageId) ?? pages[0];
  useEffect(() => {
    if (!selectedPage?.candidates.length) return;
    if (!selectedPage.candidates.some((candidate) => candidate.id === selectedCandidateId)) setSelectedCandidateId(selectedPage.decision?.candidate_id ?? selectedPage.candidates[0].id);
  }, [selectedPage, selectedCandidateId]);
  const selectedCandidate = selectedPage?.candidates.find((candidate) => candidate.id === selectedCandidateId) ?? selectedPage?.candidates[0];
  useEffect(() => {
    if (!publishedRecipes.length || publishedRecipes.some((item) => item.id === recipeId)) return;
    const first = publishedRecipes[0];
    setRecipeId(first.id);
    setQuality(recipeQuality(first));
  }, [publishedRecipes, recipeId]);
  useEffect(() => {
    if (!isGoldenDemo || !publishedRecipes.some((item) => item.id === "commerce-lifestyle-demo-v1")) return;
    setRecipeId("commerce-lifestyle-demo-v1");
    setQuality("high");
  }, [isGoldenDemo, publishedRecipes]);
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
  async function recomposed() { setMessage("本页已提交更新；进度会自动刷新，完成后请重新确认该页面。"); await onRefresh(); }
  async function regenerate(pageId: string) { setBusy(`regenerate-${pageId}`); setError(""); setMessage(""); try { await api.regeneratePage(projectId, pageId, recipeId, quality === recipeDefaultQuality ? undefined : quality); setMessage(`单页已按 ${qualityLabel(quality)} 质量重新提交。`); await onRefresh(); } catch (reason) { setError(reason instanceof Error ? reason.message : "单页重生成失败"); } finally { setBusy(""); } }
  async function saveAsRecipe() { setBusy("recipe"); setError(""); try { const recipe = await api.createRecipeCandidate(projectId, `${snapshot?.project.profile.sku ?? "商品"}验证配方`); setMessage(`已生成配方草稿：${recipe.name}，请到固定配置中测试并发布。`); } catch (reason) { setError(reason instanceof Error ? reason.message : "配方沉淀失败"); } finally { setBusy(""); } }
  if (mode === "review" && snapshot && selectedPage) return <ReviewWorkbench
    projectId={projectId}
    pages={pages}
    selectedPage={selectedPage}
    selectedCandidate={selectedCandidate}
    selectedPageId={selectedPageId}
    selectedCandidateId={selectedCandidateId}
    referenceUrls={referenceUrls}
    disabled={!!busy || isProductionActive}
    onSelectPage={setSelectedPageId}
    onSelectCandidate={setSelectedCandidateId}
    onRefresh={onRefresh}
    onRecomposed={recomposed}
  />;
  return <section className="panel production-panel production-workbench-shell">
    <div className="panel-heading planning-heading"><div><h3>图片生产、质检与审核</h3><p>配方提供默认质量；本次生产可以临时覆盖，不会修改原配方。</p></div><div className="production-controls"><div className="production-config"><label><span>生成配方</span><select aria-label="生成配方" value={recipeId} disabled={!!busy || isProductionActive} onChange={(event) => { const nextId = event.target.value; setRecipeId(nextId); setQuality(recipeQuality(publishedRecipes.find((item) => item.id === nextId))); }}>{publishedRecipes.map((recipe) => <option key={recipe.id} value={recipe.id}>{recipe.name} V{recipe.version}</option>)}</select></label><label><span>本次质量</span><select aria-label="本次生成质量" value={quality} disabled={!!busy || isProductionActive} onChange={(event) => setQuality(event.target.value)}><option value={recipeDefaultQuality}>按配方默认 · {qualityLabel(recipeDefaultQuality)}</option>{["low", "medium", "high"].filter((item) => item !== recipeDefaultQuality).map((item) => <option key={item} value={item}>{qualityLabel(item)}</option>)}</select></label></div><div className="button-row">{canExport && <button className="ghost-button" disabled={!!busy || isProductionActive} onClick={() => void saveAsRecipe()}>{busy === "recipe" ? "保存中…" : "沉淀为配方"}</button>}{hasResults && !isProductionActive && <button className="secondary" disabled={!!busy} onClick={() => void start(true)}>{busy === "regenerate" ? "重新生产中…" : "整套重新生产"}</button>}<button className="primary" disabled={!!busy || isProductionActive || (hasResults && !canExport && failedJobs === 0)} onClick={() => canExport ? void exportResult() : void start(failedJobs > 0)}>{busy === "start" || busy === "regenerate" ? "正在提交…" : busy === "export" ? "正在打包…" : isProductionActive ? "生产进行中…" : canExport ? "导出正式结果" : failedJobs > 0 ? "重试生产" : hasResults ? "等待确认后导出" : "开始生产"}</button></div></div></div>
    {referenceAssets.length > 0
      ? <div className="notice success reference-binding" role="status"><strong>已绑定 {referenceAssets.length} 张参考图</strong><span>本次生产会输入：{referenceAssets.map((asset) => asset.file_name).join("、")}</span></div>
      : <div className="notice warning reference-binding" role="status"><strong>未检测到已上传并绑定的参考图</strong><span>本次会使用纯文本生图。请先在上方“参考素材”区域选择图片并点击“上传并绑定”。</span></div>}
    {isGoldenDemo && <div className="notice success reference-binding"><strong>黄金演示预设已加载</strong><span>2048×2048 · High · 高端生活场景演示配方 · 单候选。绑定商品图后即可开始生产。</span></div>}
    {immediateActionLabel && <OperationFeedback label={immediateActionLabel} detail="请求正在提交，请勿重复点击。" compact />}
    {snapshot && hasJobs && <ProductionProgress total={pages.length} completed={completedJobs} failed={failedJobs} active={activeJobs} percent={overallProgress} />}
    {error && <div className="notice error">{error}</div>}
    {message && <div className="notice success">{message}</div>}
    {downloadUrl && <div className="notice success">正式结果已生成：<a href={downloadUrl}>下载 ZIP 交付包</a></div>}
    {!snapshot || !hasJobs ? <div className="empty-state inline-empty">确认规划后即可开始生产；提交后这里会显示实时进度。</div> : <div className="production-workbench">
      <aside className="production-page-rail"><header><strong>页面列表</strong><span>{pages.length}</span></header>{pages.map((row) => <button key={row.page.id} className={selectedPage?.page.id === row.page.id ? "active" : ""} onClick={() => setSelectedPageId(row.page.id)}><span className="page-number">{String(row.page.order).padStart(2, "0")}</span><span><strong>{row.page.title}</strong><small>{pageTypeLabel(row.page.page_type)}</small></span>{row.job && <StatusBadge status={row.decision?.decision === "approved" ? "approved" : row.job.status} />}</button>)}</aside>
      <div className="production-focus">{selectedPage && <><div className="production-page-head"><div><span>第 {selectedPage.page.order} 页 · {pageTypeLabel(selectedPage.page.page_type)}</span><h4>{selectedPage.page.title}</h4></div><div>{selectedPage.candidates.length > 0 && <button className="ghost-button mini" disabled={!!busy || isProductionActive} onClick={() => void regenerate(selectedPage.page.id)}><Icon name="refresh" />{busy === `regenerate-${selectedPage.page.id}` ? "重生成中…" : "重新生成本页"}</button>}{selectedPage.job && <StatusBadge status={selectedPage.job.status} />}</div></div><PageJobState job={selectedPage.job} candidates={selectedPage.candidates} />{selectedPage.job?.error && <div className="notice error">{selectedPage.job.error}</div>}{selectedCandidate ? <div className="production-candidate-view"><div className="production-canvas"><span className="production-image-frame"><img src={api.resolveUrl(selectedCandidate.composed_url)} alt={`第 ${selectedPage.page.order} 页候选 ${selectedCandidate.candidate_index}`} /></span></div><div className="candidate-filmstrip">{selectedPage.candidates.map((candidate) => <button key={candidate.id} className={candidate.id === selectedCandidate.id ? "active" : ""} onClick={() => setSelectedCandidateId(candidate.id)}><img src={api.resolveUrl(candidate.composed_url)} alt="" /><span>候选 {candidate.candidate_index}</span></button>)}</div></div> : <div className="production-placeholder"><Icon name="image" size={34}/><strong>{selectedPage.job?.status === "failed" ? "本页生产失败" : "等待候选图"}</strong><p>任务开始后，候选图会在这里逐步出现。</p></div>}</> }</div>
      <aside className="production-inspector"><h4>生成概览</h4><Info label="生成配方" value={selectedRecipe ? `${selectedRecipe.name} V${selectedRecipe.version}` : "—"}/><Info label="本次质量" value={qualityLabel(quality)}/><Info label="参考素材" value={`${referenceAssets.length} 张`}/>{selectedCandidate && <><div className="inspector-section"><h4>质检状态</h4><StatusBadge status={selectedCandidate.qa?.status ?? "review"}/><strong className="candidate-score">{selectedCandidate.score} 分</strong></div><div className="inspector-section"><h4>质检问题</h4>{selectedCandidate.qa?.issues.length ? selectedCandidate.qa.issues.slice(0, 4).map((issue, index) => <div className={`inspector-issue severity-${issue.severity.toLowerCase()}`} key={`${issue.code}-${index}`}><b>{issue.severity}</b><span>{issue.message}</span></div>) : <p className="muted-copy">未发现阻塞问题</p>}</div></>}</aside>
    </div>}
  </section>;
}

function ReviewWorkbench({ projectId, pages, selectedPage, selectedCandidate, selectedPageId, selectedCandidateId, referenceUrls, disabled, onSelectPage, onSelectCandidate, onRefresh, onRecomposed }: {
  projectId: string;
  pages: ProductionSnapshot["pages"];
  selectedPage: ProductionSnapshot["pages"][number];
  selectedCandidate?: ProductionSnapshot["pages"][number]["candidates"][number];
  selectedPageId: string;
  selectedCandidateId: string;
  referenceUrls: string[];
  disabled: boolean;
  onSelectPage: (id: string) => void;
  onSelectCandidate: (id: string) => void;
  onRefresh: () => Promise<void>;
  onRecomposed: () => Promise<void>;
}) {
  const [showOverlay, setShowOverlay] = useState(true);
  const [zoom, setZoom] = useState(75);
  const [compareMode, setCompareMode] = useState<"side" | "slider">("side");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [skipQa, setSkipQa] = useState(false);
  const [error, setError] = useState("");
  const [showTypography, setShowTypography] = useState(false);
  const [showEdit, setShowEdit] = useState(false);
  const issues = selectedCandidate?.qa?.issues ?? [];
  const blocking = issues.some((issue) => ["P0", "P1"].includes(issue.severity));
  const layout = selectedCandidate?.qa?.evidence?.layout as { canvas?: number[]; safe_area?: number[]; text_bbox?: number[]; subject_bbox?: number[] } | undefined;
  const overlayStyle = (bbox?: number[]) => {
    const canvas = layout?.canvas ?? [900, 1200];
    return bbox?.length === 4 ? { left: `${bbox[0] / canvas[0] * 100}%`, top: `${bbox[1] / canvas[1] * 100}%`, width: `${(bbox[2] - bbox[0]) / canvas[0] * 100}%`, height: `${(bbox[3] - bbox[1]) / canvas[1] * 100}%` } : undefined;
  };
  async function review(decision: "approved" | "rejected") {
    if (!selectedCandidate) return;
    setBusy(true); setError("");
    try { await api.reviewCandidate(selectedCandidate.id, decision, reason, skipQa); await onRefresh(); }
    catch (value) { setError(value instanceof Error ? value.message : "审核失败"); }
    finally { setBusy(false); }
  }
  async function runQa() {
    if (!selectedCandidate) return;
    setBusy(true); setError("");
    try { await api.runCandidateQa(selectedCandidate.id); setSkipQa(false); await onRefresh(); }
    catch (value) { setError(value instanceof Error ? value.message : "手动质检失败"); }
    finally { setBusy(false); }
  }
  return <section className="review-workbench">
    <aside className="review-page-rail"><header><strong>页面列表</strong><span>{pages.length}</span></header><div className="review-summary"><span className="success">通过 {pages.filter((row) => row.decision?.decision === "approved").length}</span><span className="warning">待复核 {pages.filter((row) => !row.decision).length}</span><span className="danger">不通过 {pages.filter((row) => row.decision?.decision === "rejected").length}</span></div>{pages.map((row) => { const status = row.decision?.decision === "approved" ? "approved" : row.decision?.decision === "rejected" ? "rejected" : row.candidates[0]?.qa?.status ?? row.job?.status ?? "pending"; return <button key={row.page.id} className={selectedPageId === row.page.id ? "active" : ""} onClick={() => onSelectPage(row.page.id)}><span className="page-number">{String(row.page.order).padStart(2, "0")}</span><span><strong>{row.page.title}</strong><small>{row.candidates.length} 个候选 · {row.candidates[0]?.qa?.issues.length ?? 0} 个问题</small></span><StatusBadge status={status} /></button>; })}</aside>
    <div className="review-stage-column">
      <header className="review-toolbar"><div><strong>第 {selectedPage.page.order} 页 · {selectedPage.page.title}</strong></div><div className="segmented" aria-label="对比模式" title={selectedPage.candidates.length < 2 ? "至少需要 2 个候选才能对比" : undefined}><button disabled={selectedPage.candidates.length < 2} className={compareMode === "side" ? "active" : ""} onClick={() => setCompareMode("side")}>并排</button><button disabled={selectedPage.candidates.length < 2} className={compareMode === "slider" ? "active" : ""} onClick={() => setCompareMode("slider")}>滑杆</button></div><div className="zoom-group"><IconButton icon="zoom-out" label="缩小" onClick={() => setZoom((value) => Math.max(10, value - 25))}/><span>{zoom}%</span><IconButton icon="zoom-in" label="放大" onClick={() => setZoom((value) => Math.min(400, value + 25))}/></div><button className={`overlay-control ${showOverlay ? "active" : ""}`} aria-pressed={showOverlay} onClick={() => setShowOverlay((value) => !value)}>标注图层</button><IconButton icon="fit" label="适合视口" onClick={() => setZoom(75)}/></header>
      <div className="review-stage">{selectedCandidate ? <div className="review-image-frame" style={{ width: `${Math.max(42, zoom / .75)}%` }}><img src={api.resolveUrl(selectedCandidate.composed_url)} alt={`候选 ${selectedCandidate.candidate_index}`} />{showOverlay && <>{layout?.safe_area && <i className="qa-box safe" style={overlayStyle(layout.safe_area)} />}{layout?.subject_bbox && <i className="qa-box subject" style={overlayStyle(layout.subject_bbox)} />}{layout?.text_bbox && <i className="qa-box text selected" style={overlayStyle(layout.text_bbox)} />}</>}</div> : <div className="production-placeholder"><Icon name="review" size={36}/><strong>本页还没有候选图</strong></div>}</div>
      <div className="review-filmstrip"><div><strong>同页候选</strong><span>{selectedPage.candidates.length}</span></div>{selectedPage.candidates.map((candidate) => <button key={candidate.id} className={selectedCandidateId === candidate.id ? "active" : ""} onClick={() => onSelectCandidate(candidate.id)}><img src={api.resolveUrl(candidate.composed_url)} alt={`候选 ${candidate.candidate_index}`} /><span>候选 {candidate.candidate_index}</span></button>)}</div>
      {selectedCandidate && !selectedCandidate.qa && <div className="qa-choice"><div className="notice info"><b>尚未执行质检</b><span>可以现在执行自动质检，也可以明确跳过并由人工确认。</span></div><button className="secondary" disabled={busy} onClick={() => void runQa()}>{busy ? "质检中…" : "手动执行质检"}</button><label><input type="checkbox" checked={skipQa} onChange={(event) => setSkipQa(event.target.checked)}/>跳过自动质检，以人工判断确认</label></div>}
    </div>
    <aside className="review-inspector"><section><h3>质检概览</h3><div className="qa-overview"><strong>{issues.length}</strong><span>总问题</span><div>{["P0", "P1", "P2", "P3"].map((severity) => <p key={severity}><i className={`severity-dot ${severity.toLowerCase()}`}/>{severity}<b>{issues.filter((issue) => issue.severity === severity).length}</b></p>)}</div></div></section><section><div className="inspector-heading"><h3>问题列表</h3><span>{issues.length}</span></div>{issues.length ? <div className="review-issues">{issues.map((issue, index) => <article key={`${issue.code}-${index}`} className={`severity-${issue.severity.toLowerCase()} ${index === 0 ? "selected" : ""}`}><header><b>{issue.severity}</b><strong>{issue.message}</strong><span>#{index + 1}</span></header><p>{issue.repair || selectedCandidate?.qa?.suggested_fix || "请人工检查并修正后重新提交。"}</p><button>查看标注</button></article>)}</div> : <div className="qa-pass-state"><Icon name="check"/><strong>未发现阻塞问题</strong></div>}</section><section><h3>审核操作</h3>{blocking && <div className="notice warning">存在高风险问题；通过前需要填写覆盖理由。</div>}<textarea rows={3} value={reason} onChange={(event) => setReason(event.target.value)} placeholder={blocking ? "填写高风险问题覆盖理由" : "填写审核备注（驳回时必填）"}/>{error && <div className="notice error">{error}</div>}<div className="review-actions"><button className="secondary danger" disabled={busy || disabled || !reason.trim()} onClick={() => void review("rejected")}>驳回</button><button className="primary" disabled={busy || disabled || (blocking && !reason.trim())} onClick={() => void review("approved")}>通过</button></div><div className="review-tools"><button className="ghost-button" disabled={!selectedCandidate || busy} onClick={() => { setShowTypography((value) => !value); setShowEdit(false); }}>文字重排</button><button className="ghost-button" disabled={!selectedCandidate || busy} onClick={() => { setShowEdit((value) => !value); setShowTypography(false); }}>图像调整</button></div>{selectedCandidate && showTypography && <TypographyEditor projectId={projectId} pageId={selectedPage.page.id} candidate={selectedCandidate} onCancel={() => setShowTypography(false)} onComplete={async () => { setShowTypography(false); await onRecomposed(); }}/>} {selectedCandidate && showEdit && <CandidateEditPanel candidate={selectedCandidate} disabled={busy || disabled} onCancel={() => setShowEdit(false)} onSubmitted={async () => { setShowEdit(false); await onRecomposed(); }}/>}</section><section className="audit-section"><h3>审核记录</h3><p><span className="audit-dot"/><strong>{selectedPage.decision ? statusLabel(selectedPage.decision.decision) : "等待审核"}</strong><small>{selectedPage.decision?.override_reason || "当前候选尚未形成最终审核决策。"}</small></p></section></aside>
  </section>;
}

function ProductionProgress({ total, completed, failed, active, percent }: { total: number; completed: number; failed: number; active: number; percent: number }) {
  const processed = completed + failed;
  const queued = Math.max(0, total - processed - active);
  const title = active > 0 ? "生产与质检正在进行" : failed > 0 ? "生产已结束，存在失败页面" : "图片生产已完成";
  return <div className={`production-progress ${failed > 0 && active === 0 ? "has-error" : ""}`} role="status" aria-live="polite">
    <div className="progress-heading"><div><span className={active > 0 ? "spinner" : "progress-status-dot"} aria-hidden="true" /><div><strong>{title}</strong><small>进度按页面计算，页面内部还会依次完成生图、OCR 与 LLM 质检。</small></div></div><b>{percent}%</b></div>
    <div className="progress-track production-progress-track" role="progressbar" aria-label="生产进度" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent}><span style={{ width: `${percent}%` }} /></div>
    <div className="production-stats"><span>已完成 <b>{completed}</b></span><span>处理中 <b>{active}</b></span><span>排队 <b>{queued}</b></span><span className={failed ? "failed" : ""}>失败 <b>{failed}</b></span><span>共 {total} 页</span></div>
  </div>;
}

function PageJobState({ job, candidates }: { job: ProductionSnapshot["pages"][number]["job"]; candidates: ProductionSnapshot["pages"][number]["candidates"] }) {
  const startedAt = typeof job?.trace.started_at === "string" ? job.trace.started_at : "";
  const completedAt = typeof job?.trace.completed_at === "string" ? job.trace.completed_at : "";
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
  const elapsedUntil = completedAt ? Date.parse(completedAt) : clock;
  const elapsedSeconds = startedAt
    ? Math.max(0, Math.floor((elapsedUntil - Date.parse(startedAt)) / 1000))
    : 0;
  if (!job) return null;
  const progress = jobProgress(job);
  const stage = typeof job.trace.stage === "string" ? job.trace.stage : "running";
  const stageLabel = typeof job.trace.stage_label === "string" ? job.trace.stage_label : jobStageLabel(stage);
  const candidateIndex = typeof job.trace.candidate_index === "number" ? job.trace.candidate_index : 0;
  const candidateTotal = typeof job.trace.candidate_count === "number" ? job.trace.candidate_count : 0;
  const candidateState = candidateIndex && candidateTotal ? ` · 候选 ${candidateIndex}/${candidateTotal}` : "";
  if (job.status === "running") return <div className="page-job-state running" role="status" aria-live="polite"><span className="spinner" aria-hidden="true" /><div><strong>{stageLabel}</strong><small>{referenceState}{candidateState} · 第 {job.attempt}/{job.max_attempts} 次尝试 · 已运行 {formatElapsed(elapsedSeconds)} · {progress}%</small></div><div className="page-job-progress" role="progressbar" aria-label={stageLabel} aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress}><span style={{ width: `${progress}%` }} /></div></div>;
  if (job.status === "queued") return <div className="page-job-state queued" role="status"><span className="queue-dot" aria-hidden="true" /><div><strong>等待处理</strong><small>{referenceState} · 前面的页面完成后会自动开始。</small></div></div>;
  if (job.status === "completed") return <div className="page-job-state completed"><span className="progress-status-dot" aria-hidden="true" /><div><strong>生成与质检已完成</strong><small>{referenceState} · 用时 {formatElapsed(elapsedSeconds)} · 已生成 {candidateCount} 个候选，请选择并确认最终图片。</small></div></div>;
  return <div className="page-job-state failed"><span aria-hidden="true">!</span><div><strong>本页生产失败</strong><small>可查看下方错误详情，修复后点击“重试生产”。</small></div></div>;
}

function formatElapsed(totalSeconds: number) {
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return minutes > 0 ? `${minutes}分${String(seconds).padStart(2, "0")}秒` : `${seconds}秒`;
}

function jobProgress(job: ProductionSnapshot["pages"][number]["job"]) {
  if (!job) return 0;
  if (["completed", "failed"].includes(job.status)) return 100;
  const value = job.trace.progress;
  return typeof value === "number" ? Math.max(0, Math.min(100, Math.round(value))) : job.status === "running" ? 5 : 0;
}

function jobStageLabel(stage: string) {
  return ({
    preparing: "准备 Prompt、模板与参考素材",
    generating_background: "Azure 正在生成无商品场景底图",
    compositing_product: "合成参考商品图层",
    compositing_text: "执行确定性文字排版",
    checking_base_text: "OCR 检查底图留白区",
    checking_reference: "核对参考商品与布局",
    ocr_output: "OCR 校验最终营销文案",
    ocr_reference: "OCR 读取参考商品面板",
    llm_review: "LLM 审查视觉质量与参考一致性",
    candidate_completed: "候选图片与 QA 已完成",
    ranking: "汇总 QA 证据并排序候选",
    finalizing: "保存候选、图层和 QA 结果",
    understanding_edit: "理解单图修改要求并建立验收计划",
    editing_candidate: "Azure 正在定向修改所选候选图",
    checking_edit: "对比修改前后并执行局部质检",
  } as Record<string, string>)[stage] ?? "正在生成图片并执行质检";
}

function CandidateCard({ projectId, pageId, candidate, history, referenceUrls, selected, disabled, onReviewed, onRecomposed }: { projectId: string; pageId: string; candidate: ProductionSnapshot["pages"][number]["candidates"][number]; history: ProductionSnapshot["pages"][number]["history"]; referenceUrls: string[]; selected: boolean; disabled: boolean; onReviewed: () => Promise<void>; onRecomposed: () => Promise<void> }) {
  const [reason, setReason] = useState(""); const [busy, setBusy] = useState(false); const [error, setError] = useState(""); const [showQaOverlay, setShowQaOverlay] = useState(false); const [showTypography, setShowTypography] = useState(false); const [showEdit, setShowEdit] = useState(false);
  const blocking = candidate.qa?.issues.some((issue) => ["P0", "P1"].includes(issue.severity));
  const layout = candidate.qa?.evidence?.layout as { canvas?: number[]; safe_area?: number[]; text_bbox?: number[]; subject_bbox?: number[] } | undefined;
  const technicalIssues = candidate.qa?.issues.filter((issue) => issue.code.includes("unavailable")) ?? [];
  const qualityIssues = candidate.qa?.issues.filter((issue) => !issue.code.includes("unavailable")) ?? [];
  const generatorMetadata = candidate.metadata?.generator as { size?: string; layout?: { canvas_size?: string } } | undefined;
  const candidateAspectRatio = imageAspectRatio(generatorMetadata?.size ?? generatorMetadata?.layout?.canvas_size);
  const overlay = (bbox?: number[]) => { const canvas = layout?.canvas ?? [900, 1200]; return bbox?.length === 4 ? { left: `${bbox[0] / canvas[0] * 100}%`, top: `${bbox[1] / canvas[1] * 100}%`, width: `${(bbox[2] - bbox[0]) / canvas[0] * 100}%`, height: `${(bbox[3] - bbox[1]) / canvas[1] * 100}%` } : undefined; };
  async function review(decision: "approved" | "rejected") { setBusy(true); setError(""); try { await api.reviewCandidate(candidate.id, decision, reason); await onReviewed(); } catch (value) { setError(value instanceof Error ? value.message : "审核失败"); } finally { setBusy(false); } }
  return <div className={`candidate-card ${selected ? "selected" : ""}`}>
    <div className="candidate-image" style={{ aspectRatio: candidateAspectRatio }}>
      <img src={api.resolveUrl(candidate.composed_url)} alt={`候选 ${candidate.candidate_index}`} />
      {showQaOverlay && <>
        {layout?.safe_area && <i className="qa-box safe" style={overlay(layout.safe_area)} />}
        {layout?.subject_bbox && <i className="qa-box subject" style={overlay(layout.subject_bbox)} />}
        {layout?.text_bbox && <i className="qa-box text" style={overlay(layout.text_bbox)} />}
      </>}
      <span>排名 #{candidate.rank}</span>
      {layout && <button type="button" className={`qa-overlay-toggle ${showQaOverlay ? "active" : ""}`} aria-pressed={showQaOverlay} onClick={() => setShowQaOverlay((visible) => !visible)}>{showQaOverlay ? "隐藏质检框" : "显示质检框"}</button>}
      {referenceUrls.length > 0 && <div className="reference-thumb"><img src={referenceUrls[0]} alt="商品参考图" /><small>{referenceUrls.length} 张参考图</small></div>}
    </div>
    <div className="candidate-summary">
      <div><strong>{candidate.score} 分</strong><StatusBadge status={candidate.qa?.status ?? "review"} /></div>
      {technicalIssues.length > 0 && <div className="notice warning qa-technical-state"><b>自动审查服务降级</b><span>{technicalIssues.map((issue) => issue.message).join("；")}</span></div>}
      {qualityIssues.length ? <ul className="qa-issue-list">{qualityIssues.map((issue, index) => <li key={`${issue.code}-${index}`} className={`severity-${issue.severity.toLowerCase()}`}><b>{issue.severity}</b><span>{issue.message}</span></li>)}</ul> : technicalIssues.length ? <p>未发现已证实的图片质量问题，当前需要人工确认。</p> : <p>未发现阻塞问题</p>}
      <details className="qa-severity-legend"><summary>P0 / P1 / P2 / P3 是什么？</summary><p><b>P0</b> 系统硬性阻断；<b>P1</b> 重大问题，会阻止直接确认；<b>P2</b> 需要关注或人工确认；<b>P3</b> 提示或轻微建议。</p></details>
      {candidate.qa?.repair_applied && <small>已执行自动排版或一轮图片修复</small>}
      <details><summary>查看分层文件与质检证据</summary>
        <div className="layer-links">
          {candidate.background_url && <a href={api.resolveUrl(candidate.background_url)} target="_blank" rel="noreferrer">场景背景</a>}
          {candidate.product_layer_url && <a href={api.resolveUrl(candidate.product_layer_url)} target="_blank" rel="noreferrer">原样商品层</a>}
          <a href={api.resolveUrl(candidate.base_url)} target="_blank" rel="noreferrer">模型生成图（无营销文字）</a>
          <a href={api.resolveUrl(candidate.text_layer_url)} target="_blank" rel="noreferrer">文字层</a>
          <a href={api.resolveUrl(candidate.composed_url)} target="_blank" rel="noreferrer">最终合成图</a>
        </div>
        <pre>{JSON.stringify(candidate.qa?.evidence, null, 2)}</pre>
      </details>
      {blocking && <input className="override-input" value={reason} onChange={(event) => setReason(event.target.value)} placeholder="P0/P1 人工覆盖原因（必填）" />}
      {busy && <OperationFeedback label="正在提交审核结果" compact />}
      {error && <div className="notice error">{error}</div>}
      {showTypography && <TypographyEditor projectId={projectId} pageId={pageId} candidate={candidate} onCancel={() => setShowTypography(false)} onComplete={async () => { setShowTypography(false); await onRecomposed(); }} />}
      {showEdit && <CandidateEditPanel candidate={candidate} disabled={busy || disabled} onCancel={() => setShowEdit(false)} onSubmitted={async () => { setShowEdit(false); await onRecomposed(); }} />}
      <CandidateHistory history={history} currentId={candidate.id} />
      <div className="candidate-actions"><button className="ghost-button" disabled={busy || disabled} onClick={() => { setShowTypography((visible) => !visible); setShowEdit(false); }}>{showTypography ? "收起排版" : "调整文字排版"}</button><button className="ghost-button" disabled={busy || disabled} onClick={() => { setShowEdit((visible) => !visible); setShowTypography(false); }}>{showEdit ? "收起修改" : "继续修改此图"}</button><button className="secondary" disabled={busy || disabled} onClick={() => void review("rejected")}>{busy ? "提交中…" : "不采用"}</button><button className="primary" disabled={busy || disabled || selected} onClick={() => void review("approved")}>{busy ? "提交中…" : selected ? "已确认" : "确认此图"}</button></div>
    </div>
  </div>;
}

function ProjectTable({ projects, onOpen, onRefresh }: { projects: Project[]; onOpen: (id: string) => void; onRefresh: () => Promise<void> }) {
  const [busy, setBusy] = useState(""); const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  async function clone(project: Project) { setBusy(project.id); setError(""); try { const copied = await api.cloneProject(project.id); await onRefresh(); onOpen(copied.id); } catch (reason) { setError(reason instanceof Error ? reason.message : "复制失败"); } finally { setBusy(""); } }
  const showcases = projects.filter((project) => project.id.startsWith("showcase-"));
  const regularProjects = projects.filter((project) => !project.id.startsWith("showcase-") && project.status !== "archived").filter((project) => status === "all" || project.status === status).filter((project) => `${project.name} ${project.profile.name} ${project.profile.sku} ${project.profile.model}`.toLowerCase().includes(query.toLowerCase()));
  return <div className="project-catalog">
    <div className="filter-bar"><label className="search-field"><Icon name="search"/><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索项目、商品或 SKU" aria-label="搜索项目"/></label><label className="filter-select"><Icon name="filter"/><select value={status} onChange={(event) => setStatus(event.target.value)} aria-label="按状态筛选"><option value="all">全部状态</option><option value="draft">草稿</option><option value="planned">已规划</option><option value="producing">生产中</option><option value="reviewing">审核中</option><option value="completed">已完成</option></select></label><span className="filter-count">{regularProjects.length} 个项目</span></div>
    {showcases.length > 0 && <section className="panel showcase-panel">
      <div className="panel-heading"><h3>内置示例项目</h3><p>部署后直接可见，无需调用生图模型；可进入查看分层结果，或复制为自己的项目继续调整。</p></div>
      <div className="showcase-grid">{showcases.map((project) => <article key={project.id} className="showcase-card">
        <button className="showcase-image" onClick={() => onOpen(project.id)}><img src={api.resolveUrl(`/api/candidates/${project.id}-candidate-1/files/composed`)} alt={project.name} /></button>
        <div><span className="demo-tag">内置审计示例</span><strong>{project.name.replace("[示例] ", "")}</strong><small>{showcaseSize(project.id)} · High · 独立文字层</small></div>
        <div className="showcase-actions"><button className="table-action" disabled={!!busy} onClick={() => void clone(project)}>{busy === project.id ? "复制中…" : "以此创建项目"}</button><button className="table-action" onClick={() => onOpen(project.id)}>查看完整结果 →</button></div>
      </article>)}</div>
    </section>}
    <section className="panel"><div className="panel-heading"><h3>最近项目</h3><p>进入项目后按商品资料、内容规划、图片生产、质检审核和交付导出推进。</p></div>{busy && <OperationFeedback label="正在复制项目" detail="正在复制商品档案与页面规划。" compact />}{error && <div className="notice error">{error}</div>}{regularProjects.length === 0 ? <div className="empty-state"><strong>{query || status !== "all" ? "没有符合条件的项目" : "还没有自己的商品项目"}</strong><p>{query || status !== "all" ? "调整搜索或筛选条件后重试。" : "可以复制示例或创建第一个商品项目。"}</p>{(query || status !== "all") && <button className="secondary" onClick={() => { setQuery(""); setStatus("all"); }}>清除筛选</button>}</div> : <div className="table-wrap"><table><thead><tr><th>项目</th><th>SKU / 型号</th><th>品类</th><th>状态</th><th>创建时间</th><th /></tr></thead><tbody>{regularProjects.map((project) => <tr key={project.id} tabIndex={0} onKeyDown={(event) => event.key === "Enter" && onOpen(project.id)}><td><strong>{project.name}</strong><small>{project.profile.name}</small></td><td>{project.profile.sku}<small>{project.profile.model || "未填写型号"}</small></td><td>{project.profile.category}</td><td><StatusBadge status={project.status} /></td><td>{formatDate(project.created_at)}</td><td><div className="table-actions"><button className="table-action" disabled={!!busy} onClick={() => void clone(project)}><Icon name="copy"/> {busy === project.id ? "复制中…" : "复制"}</button><button className="table-action" disabled={!!busy} onClick={() => onOpen(project.id)}>进入项目</button></div></td></tr>)}</tbody></table></div>}</section>
  </div>;
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
  const [promptName, setPromptName] = useState("");
  const [promptBody, setPromptBody] = useState("为{{product_name}}制作高端电商广告图。页面目标：{{visual_goal}}。综合全部商品外观与细节参考图，在真实空间中重新生成同一商品；允许调整拍摄角度、透视、环境光影和效果，但保持商品轮廓、比例、颜色、材质与关键结构一致。{{scene_prompt_hint}}。{{composition_instruction}}。最终文字由后期排版，生成图不要新增营销文字。");
  const [recipeName, setRecipeName] = useState("");
  const [recipePrompt, setRecipePrompt] = useState("");
  const [newRecipeQuality, setNewRecipeQuality] = useState("high");
  const [newRecipeReferenceStrategy, setNewRecipeReferenceStrategy] = useState("model_edit");
  const [newRecipeAutoRepair, setNewRecipeAutoRepair] = useState("0");
  const [recipeCandidates, setRecipeCandidates] = useState(1);
  const [recipeTemplates, setRecipeTemplates] = useState<string[]>([]);
  const [previewTemplateId, setPreviewTemplateId] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");

  const refresh = useCallback(async () => {
    const [templateRows, recipeRows, promptRows] = await Promise.all([
      api.listTemplates(), api.listRecipes(), api.listPrompts(),
    ]);
    setTemplates(templateRows);
    setRecipes(recipeRows);
    setPrompts(promptRows);
    setRecipePrompt((current) => current || promptRows.find((item) => item.status === "published")?.id || "");
    setRecipeTemplates((current) => current.length ? current : templateRows.map((item) => item.id));
    setPreviewTemplateId((current) => current || templateRows[0]?.id || "");
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const publishedPrompts = prompts.filter((item) => item.status === "published");
  const selectedPrompt = prompts.find((item) => item.id === recipePrompt) ?? publishedPrompts[0];
  const previewTemplate = templates.find((item) => item.id === previewTemplateId) ?? templates[0];
  const activeModel = recipes.find((item) => item.status === "published")?.model ?? "azure-gpt-image";

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
      <div className="panel-heading"><h3>一张图是怎么生成的</h3><p>模型综合多张商品参考图生成商品与场景；准确营销文案最后单独排版。</p></div>
      <div className="recipe-flow"><article><b>1</b><strong>页面模板</strong><span>画布尺寸、文字区、商品区</span></article><i>＋</i><article><b>2</b><strong>多张参考图</strong><span>共同定义商品身份与细节</span></article><i>＋</i><article><b>3</b><strong>生图 Prompt</strong><span>控制角度、场景、光影与留白</span></article><i>＋</i><article><b>4</b><strong>生成配方</strong><span>策略、质量、候选数、质检</span></article><i>→</i><article className="result"><b>5</b><strong>模型图 + 文字层</strong><span>商品与场景由模型生成，文案精确排版</span></article></div>
    </section>

    <div className="catalog-layout recipe-catalog-layout">
      <section className="panel recipe-panel">
        <div className="panel-heading"><h3>生成配方</h3><p>把生图 Prompt、参考策略、模型参数、模板范围和质检策略固定为可复用方案。</p></div>
        <div className="recipe-list">{recipes.map((recipe) => {
          const prompt = prompts.find((item) => item.id === recipe.prompt_version_id);
          return <article className={`recipe-card ${recipe.id === "commerce-lifestyle-demo-v1" ? "featured" : ""}`} key={recipe.id}><div className="recipe-card-head"><StatusBadge status={recipe.status} />{recipe.id === "commerce-lifestyle-demo-v1" && <span className="demo-tag">推荐演示</span>}</div><h3>{recipe.name}</h3><p>{prompt?.name ?? recipe.prompt_version_id}</p><div className="recipe-meta"><span>默认质量 {qualityLabel(recipeQuality(recipe))}</span><span>{referenceStrategyLabel(recipe)}</span><span>{Number(recipe.model_params.max_auto_regenerations ?? 0) > 0 ? "自动修复最多 1 次" : "单次生成"}</span><span>每页 {recipe.candidate_count} 个候选</span><span>{recipe.template_ids.length} 个模板</span></div><small>{recipe.model} · {recipe.qa_policy}</small>{recipe.status === "draft" && <button className="secondary" disabled={!!busy} onClick={() => void publishRecipe(recipe.id)}>{busy === `publish-recipe-${recipe.id}` ? "发布中…" : "发布配方"}</button>}</article>;
        })}</div>
      </section>
      <form className="panel catalog-side-form" onSubmit={createRecipe}>
        <div className="panel-heading"><h3>配置新配方</h3><p>质量是默认值，实际生产时仍可临时覆盖。</p></div>
        <div className="catalog-form">
          <Field label="配方名称"><input required disabled={!!busy} value={recipeName} onChange={(event) => setRecipeName(event.target.value)} placeholder="例如：洗衣机场景图配方" /></Field>
          <Field label="生图 Prompt"><select required disabled={!!busy} value={recipePrompt} onChange={(event) => setRecipePrompt(event.target.value)}>{publishedPrompts.map((item) => <option key={item.id} value={item.id}>{item.name} V{item.version}</option>)}</select></Field>
          <div className="form-grid compact"><Field label="默认质量"><select value={newRecipeQuality} onChange={(event) => setNewRecipeQuality(event.target.value)}><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option></select></Field><Field label="每页候选"><select value={recipeCandidates} onChange={(event) => setRecipeCandidates(Number(event.target.value))}><option value={1}>1 张</option><option value={2}>2 张</option><option value={3}>3 张</option></select></Field></div>
          <Field label="参考商品处理"><select value={newRecipeReferenceStrategy} onChange={(event) => setNewRecipeReferenceStrategy(event.target.value)}><option value="model_edit">多参考图生成商品（推荐，可生成新角度/光影）</option><option value="layered_product">原样商品贴图（仅兼容旧方案）</option></select></Field>
          <Field label="自动图片修复"><select value={newRecipeAutoRepair} onChange={(event) => setNewRecipeAutoRepair(event.target.value)}><option value="0">关闭（每候选只调用一次生图）</option><option value="1">最多自动重生 1 次</option></select></Field>
          <small className="form-help">推荐模式会把商品外观图和局部细节图一起发送给模型，由模型直接生成商品与场景；允许新角度和环境效果，并由审查综合核对全部参考图。原样贴图只用于必须像素级不变的旧流程。</small>
          <fieldset className="template-checks"><legend>适用模板</legend>{templates.map((template) => <label key={template.id}><input type="checkbox" checked={recipeTemplates.includes(template.id)} onChange={(event) => setRecipeTemplates((current) => event.target.checked ? [...current, template.id] : current.filter((id) => id !== template.id))} /><span>{template.name}<small>{template.size}</small></span></label>)}</fieldset>
          <button className="primary" disabled={!!busy}>{busy === "create-recipe" ? "保存中…" : "保存配方草稿"}</button>
        </div>
      </form>
    </div>

    <section className="panel prompt-panel">
      <div className="panel-heading"><h3>图片生成指令（Prompt）</h3><p>这里描述模型要生成的商品、角度、效果、场景和留白；真实标题、正文和字号不进入生图 Prompt。</p></div>
      <div className="prompt-runtime-preview"><div><span>选择模板查看运行时合并结果</span><select value={previewTemplateId} onChange={(event) => setPreviewTemplateId(event.target.value)}>{templates.map((template) => <option key={template.id} value={template.id}>{template.name} · {template.size}</option>)}</select></div><pre>{compilePromptPreview(selectedPrompt?.body ?? "", previewTemplate)}</pre></div>
      <div className="prompt-layout"><div className="prompt-list">{prompts.map((prompt) => <article key={prompt.id}><div><StatusBadge status={prompt.status} /><strong>{prompt.name} · V{prompt.version}</strong></div><p>{prompt.body}</p><small>{prompt.variables.map((item) => `{{${item}}}`).join(" · ") || "无变量"}</small>{prompt.status === "draft" && <button className="secondary" disabled={!!busy} onClick={() => void publishPrompt(prompt.id)}>{busy === `publish-prompt-${prompt.id}` ? "发布中…" : "发布此版本"}</button>}</article>)}</div><form className="catalog-form" onSubmit={createPrompt}><h4>新建生图 Prompt</h4><input required disabled={!!busy} value={promptName} onChange={(event) => setPromptName(event.target.value)} placeholder="Prompt 名称" /><textarea required disabled={!!busy} rows={11} value={promptBody} onChange={(event) => setPromptBody(event.target.value)} /><small className="form-help">推荐包含 {"{{visual_goal}}"}、{"{{scene_prompt_hint}}"} 和 {"{{composition_instruction}}"}。</small><button className="primary" disabled={!!busy}>{busy === "create-prompt" ? "保存中…" : "保存为草稿"}</button></form></div>
    </section>
  </div>;
}

function ProjectForm({ onClose, onCreated }: { onClose: () => void; onCreated: (projectId?: string) => Promise<void> }) {
  const [projectName, setProjectName] = useState(""); const [profile, setProfile] = useState(emptyProfile()); const [sellingPoints, setSellingPoints] = useState(""); const [parameters, setParameters] = useState("容量=12kg"); const [error, setError] = useState(""); const [saving, setSaving] = useState(false);
  const [step, setStep] = useState<1 | 2>(1);
  const [libraries, setLibraries] = useState<LayoutLibrary[]>([]); const [libraryId, setLibraryId] = useState("library-square-2048");
  useEffect(() => { void api.listLayoutLibraries().then((rows) => { setLibraries(rows); if (!rows.some((item) => item.id === libraryId) && rows[0]) setLibraryId(rows[0].id); }).catch(() => undefined); }, []);
  async function submit(event: FormEvent) { event.preventDefault(); setSaving(true); setError(""); try { const parsedParameters = Object.fromEntries(parameters.split(/\n|[;；]/).map((row) => row.trim()).filter(Boolean).map((row) => row.split(/[=：:]/, 2).map((part) => part.trim())).filter(([key, value]) => key && value)); const project = await api.createProject({ project_name: projectName, profile: { ...profile, parameters: parsedParameters, selling_points: sellingPoints.split("\n").map((item) => item.trim()).filter(Boolean) } }); await api.generatePlan(project.id, libraryId); await onCreated(project.id); } catch (reason) { setError(reason instanceof Error ? reason.message : "创建失败"); } finally { setSaving(false); } }
  const canContinue = !!(projectName.trim() && profile.sku.trim() && profile.name.trim() && profile.category.trim());
  return <Dialog title="创建商品项目" subtitle={step === 1 ? "先填写基础信息，再选择内容版式。" : "补充卖点和参数，创建后仍可继续修改。"} onClose={onClose}><div className="form-stepper" aria-label="创建步骤"><span className="active"><b>1</b>基础信息</span><i/><span className={step === 2 ? "active" : ""}><b>2</b>内容设置</span></div><form onSubmit={submit}>{step === 1 ? <><Field label="项目名称"><input required value={projectName} onChange={(event) => setProjectName(event.target.value)} placeholder="例如：X11 电商详情页" /></Field><div className="form-grid"><Field label="SKU"><input required value={profile.sku} onChange={(event) => setProfile({ ...profile, sku: event.target.value })} /></Field><Field label="型号"><input value={profile.model} onChange={(event) => setProfile({ ...profile, model: event.target.value })} /></Field><Field label="商品名称"><input required value={profile.name} onChange={(event) => { const name = event.target.value; setProfile({ ...profile, name }); if (!projectName) setProjectName(name ? `${name}内容项目` : ""); }} /></Field><Field label="品类"><input required value={profile.category} onChange={(event) => setProfile({ ...profile, category: event.target.value })} /></Field></div><div className="form-actions"><button type="button" className="secondary" onClick={onClose}>取消</button><button type="button" className="primary" disabled={!canContinue} onClick={() => setStep(2)}>下一步</button></div></> : <><LayoutLibraryPicker libraries={libraries} selectedId={libraryId} onSelect={setLibraryId} disabled={saving} /><Field label="核心卖点（每行一项）"><textarea rows={3} value={sellingPoints} onChange={(event) => setSellingPoints(event.target.value)} /></Field><Field label="商品参数（每行：名称=值）"><textarea rows={3} value={parameters} onChange={(event) => setParameters(event.target.value)} /></Field>{error && <div className="notice error">{error}</div>}<div className="form-actions"><button type="button" className="secondary" disabled={saving} onClick={() => setStep(1)}>上一步</button><button className="primary" disabled={saving}>{saving ? "正在创建…" : "创建项目"}</button></div>{saving && <OperationFeedback label="正在创建项目" detail="项目创建后会自动进入商品资料。" compact />}</>}</form></Dialog>;
}

function BatchForm({ onClose, onCreated }: { onClose: () => void; onCreated: () => Promise<void> }) {
  const [mode, setMode] = useState<"file" | "quick">("file"); const [name, setName] = useState(""); const [category, setCategory] = useState("洗衣机"); const [rows, setRows] = useState("X11|COLMO X11\nT1|COLMO T1"); const [file, setFile] = useState<File | null>(null); const [error, setError] = useState(""); const [saving, setSaving] = useState(false);
  async function submit(event: FormEvent) { event.preventDefault(); setSaving(true); setError(""); try { if (mode === "file") { if (!file) throw new Error("请选择 CSV 或 XLSX 文件"); await api.importBatch(name, file, category); } else { const skus = rows.split("\n").map((row) => row.trim()).filter(Boolean).map((row) => { const [sku, productName] = row.split("|").map((value) => value?.trim()); return { profile: { ...emptyProfile(), sku, name: productName || sku, category, model: sku }, override_config: {} }; }); await api.createBatch({ name, common_config: { recipe_id: "commerce-detail-v1" }, skus }); } await onCreated(); } catch (reason) { setError(reason instanceof Error ? reason.message : "创建失败"); } finally { setSaving(false); } }
  return <Dialog title="新建多 SKU 批次" subtitle="导入后，每个 SKU 会创建独立商品项目并共享基础配方。" onClose={onClose}><form onSubmit={submit}><div className="mode-switch"><button type="button" className={mode === "file" ? "active" : ""} onClick={() => setMode("file")}>表格导入</button><button type="button" className={mode === "quick" ? "active" : ""} onClick={() => setMode("quick")}>快速录入</button></div><Field label="批次名称"><input required value={name} onChange={(e) => setName(e.target.value)} /></Field><Field label="缺省品类"><input required value={category} onChange={(e) => setCategory(e.target.value)} /></Field>{mode === "file" ? <><Field label="SKU 文件（CSV / XLSX）"><label className="file-picker large"><input type="file" accept=".csv,.xlsx" onChange={(event) => setFile(event.target.files?.[0] ?? null)} /><span>{file?.name ?? "选择导入文件"}</span></label></Field><a className="template-download" href={api.batchImportTemplateUrl}>下载固定 CSV 模板</a></> : <Field label="SKU清单（每行：SKU|商品名称）"><textarea required rows={7} value={rows} onChange={(e) => setRows(e.target.value)} /></Field>}{error && <div className="notice error">{error}</div>}<FormActions onClose={onClose} saving={saving} label={mode === "file" ? "导入并创建" : "创建批次"} /></form></Dialog>;
}

function Metric({ label, value, hint, text = false }: { label: string; value: number | string; hint: string; text?: boolean }) { return <article className="metric-card"><p>{label}</p><strong className={text ? "metric-text" : ""}>{value}</strong><span>{hint}</span></article>; }
function Info({ label, value, wide = false }: { label: string; value: string; wide?: boolean }) { return <div className={wide ? "wide" : ""}><span>{label}</span><strong>{value}</strong></div>; }
function Dialog({ title, subtitle, onClose, children }: { title: string; subtitle: string; onClose: () => void; children: ReactNode }) {
  const titleId = useId();
  const dialogRef = useRef<HTMLElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const dialog = dialogRef.current;
    dialog?.querySelector<HTMLElement>("input, select, textarea, button")?.focus();
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); onClose(); return; }
      if (event.key !== "Tab" || !dialog) return;
      const items = Array.from(dialog.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [href]'));
      if (!items.length) return;
      const first = items[0]; const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", keydown);
    return () => { document.removeEventListener("keydown", keydown); previous?.focus(); };
  }, [onClose]);
  return <div className="dialog-backdrop" role="presentation"><section ref={dialogRef} className="dialog" role="dialog" aria-modal="true" aria-labelledby={titleId}><IconButton className="close" icon="close" label="关闭" onClick={onClose}/><h2 id={titleId}>{title}</h2><p className="dialog-subtitle">{subtitle}</p>{children}</section></div>;
}
function Field({ label, children }: { label: string; children: ReactNode }) { return <label className="field"><span>{label}</span>{children}</label>; }
function FormActions({ onClose, saving, label }: { onClose: () => void; saving: boolean; label: string }) { return <><div className="form-actions"><button type="button" className="secondary" disabled={saving} onClick={onClose}>取消</button><button className="primary" disabled={saving}>{saving ? "正在保存…" : label}</button></div>{saving && <OperationFeedback label={`正在${label}`} detail="数据正在提交，请勿关闭窗口。" compact />}</>; }
function OperationFeedback({ label, detail = "", compact = false }: { label: string; detail?: string; compact?: boolean }) { return <div className={`operation-feedback ${compact ? "compact" : ""}`} role="status" aria-live="polite"><span className="spinner" aria-hidden="true" /><div><strong>{label}</strong>{detail && <small>{detail}</small>}</div></div>; }
function StatusBadge({ status }: { status: string }) { return <span className={`badge badge-${status} badge-${statusTone(status)}`}>{statusLabel(status)}</span>; }
function projectOperationLabel(value: string) { return ({ generate: "正在提交 AI 内容规划", "apply-planning": "正在应用 AI 规划建议", save: "正在保存规划草稿", confirm: "正在确认页面规划" } as Record<string, string>)[value] ?? "正在处理"; }
function productionActionLabel(value: string) { if (!value) return ""; if (value.startsWith("recompose-")) return "正在重新排版并质检"; if (value.startsWith("regenerate-")) return "正在提交单页重生成"; return ({ start: "正在提交生产任务", regenerate: "正在提交整套重新生产", export: "正在打包正式结果", recipe: "正在沉淀配方" } as Record<string, string>)[value] ?? "正在处理生产操作"; }
function batchOperationLabel(value: string) { return ({ start: "正在提交批量生产", retry: "正在提交失败项重试", pause: "正在暂停批次", resume: "正在恢复批次", export: "正在打包批量结果" } as Record<string, string>)[value] ?? "正在处理批次操作"; }
function formatDate(value: string) { return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(value)); }
function formatBytes(value: number) { return value < 1024 * 1024 ? `${Math.max(1, Math.round(value / 1024))} KB` : `${(value / 1024 / 1024).toFixed(1)} MB`; }
function tabTitle(tab: Tab) { return tab === "projects" ? "商品项目" : tab === "batches" ? "多 SKU 批量任务" : tab === "layouts" ? "版式中心" : "生成配置"; }
function pageTypeLabel(value: string) { return ({ hero: "主视觉", selling_point: "核心卖点", function: "功能说明", scene: "生活场景", parameters: "商品参数" } as Record<string, string>)[value] ?? value; }
function usageLabel(value: Asset["usage"]) { return ({ product: "商品外观", detail: "局部细节", brand: "品牌风格", scene: "场景参考" } as Record<Asset["usage"], string>)[value]; }
function showcaseSize(projectId: string) { return projectId.includes("landscape") ? "3840×2160 横版" : projectId.includes("portrait") ? "2160×3840 竖版" : "2048×2048 方形"; }
function imageAspectRatio(value?: string) { const match = value?.match(/^(\d+)x(\d+)$/i); return match ? `${match[1]} / ${match[2]}` : "1 / 1"; }
function regionStyle(box: readonly number[]): CSSProperties {
  const [left = 0, top = 0, right = 1, bottom = 1] = box;
  return { position: "absolute", left: `${left * 100}%`, top: `${top * 100}%`, width: `${(right - left) * 100}%`, height: `${(bottom - top) * 100}%` };
}
function recipeQuality(recipe?: Recipe) {
  const quality = String(recipe?.model_params.quality ?? "high").toLowerCase();
  return ["low", "medium", "high"].includes(quality) ? quality : "high";
}
function qualityLabel(value: string) { return ({ low: "Low（快速）", medium: "Medium（均衡）", high: "High（精细）" } as Record<string, string>)[value] ?? value; }
function referenceStrategyLabel(recipe: Recipe) { return recipe.model_params.reference_strategy === "layered_product" ? "原样商品贴图（兼容）" : "多参考图生成商品"; }
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
  return `${compiled}\n\n[系统运行时追加]\n${values.composition_instruction}。综合全部商品参考图，由模型直接生成商品、角度、效果与场景；不使用商品贴图。不要生成标题、正文、标语、参数或装饰性字符。商品本体自带的真实铭牌和控制面板除外。`;
}

export default App;
