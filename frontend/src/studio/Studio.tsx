import {useCallback, useEffect, useRef, useState} from "react";
import {cleanReuse, demoUrl, mediaUrl, studio} from "./client";
import {Icon} from "./icons";
import {Modal} from "./Modal";
import {ActionMenu, PagePurposes, PlanEditor, ReviewFindings} from "./WorkspacePanels";
import {usePanelFocus} from "./usePanelFocus";
import {ServiceBanner, ServiceConfiguration, useStudioHealth} from "./ServiceStatus";
import type {Asset, Catalog, Content, DemoItem, DemoPack, Draft, LibraryEntry, PlanVersion, Results, Tool, Version} from "./types";
import {Editor, renderComposition} from "./editor";
import {downloadLongImage, downloadVersion, downloadZip} from "./export";
import "./studio.css";

const tools: {id: Tool; name: string; icon: string; description: string}[] = [
  {id: "ecom_suite", name: "电商套图", icon: "grid", description: "一个商品，一整套视觉表达"},
  {id: "a_plus_detail", name: "A+ 详情图", icon: "detail", description: "从模块规划到完整详情内容"},
  {id: "marketing_main_image", name: "营销主图", icon: "spark", description: "让商品成为画面的焦点"},
  {id: "scene_image", name: "场景图", icon: "scene", description: "把商品放进恰当的生活场景"},
  {id: "selling_point_image", name: "卖点图", icon: "image", description: "用清晰的视觉，讲好商品细节"},
];
const emptyResults: Results = {operations: [], versions: [], selections: [], review_tasks: []};
const issueLabels: Record<string, string> = {error: "明确问题", uncertain: "待确认", suggestion: "优化建议"};
const statusLabels: Record<string, string> = {queued: "等待执行", running: "处理中", done: "已完成", failed: "生成失败", unknown: "结果待确认", stopped: "已停止"};
const historyStatusLabels: Record<string, string> = {draft: "草稿", queued: "等待执行", processing: "生成中", completed: "已有结果", partial: "部分完成", failed: "生成失败", unknown: "结果待确认"};
const err = (value: unknown) => value instanceof Error ? /Failed to fetch|NetworkError/.test(value.message) ? "无法连接创作服务，请查看服务配置并重新检测。当前输入请勿关闭。" : value.message : "操作失败，请重试";
const newKey = () => crypto.randomUUID();
const canonicalJson = (value: unknown) => JSON.stringify(value, (_key, item: unknown) => {
  if (!item || typeof item !== "object" || Array.isArray(item)) return item;
  const record = item as Record<string, unknown>;
  return Object.fromEntries(Object.keys(record).sort().map(key => [key, record[key]]));
});

function rememberedTool(): Tool {
  try {const saved = localStorage.getItem("studio.tool"); return tools.find(item => item.id === saved)?.id ?? "ecom_suite";} catch {return "ecom_suite";}
}
async function loadToolDraft(tool: Tool): Promise<Draft> {
  let id: string | null = null;
  try {id = localStorage.getItem(`studio.draft.${tool}`);} catch {/* Storage may be disabled. */}
  const rows = await studio.drafts(tool);
  return rows.find(value => value.id === id) ?? rows[0] ?? studio.create(tool);
}
function isRememberedDemo(value: Draft) {
  try {return localStorage.getItem(`studio.demo.${value.tool}`) === canonicalJson({id: value.id, content: value.content});} catch {return false;}
}

function VersionVisual({version, alt}: {version: Version; alt: string}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (!version.layers.length) return;
    let live = true;
    const buffer = document.createElement("canvas");
    void renderComposition(buffer, version.base_url, version.layers).then(() => {
      if (!live || !canvas.current) return;
      canvas.current.width = buffer.width; canvas.current.height = buffer.height;
      canvas.current.getContext("2d")!.drawImage(buffer, 0, 0);
    }).catch(() => {if (live) setFailed(true);});
    return () => {live = false;};
  }, [version.id, version.base_url, version.layers]);
  if (!version.layers.length || failed) return <img src={mediaUrl(version.image_url)} alt={alt}/>;
  return <canvas ref={canvas} role="img" aria-label={alt}/>;
}

export default function Studio() {
  const service = useStudioHealth();
  const [serviceOpen, setServiceOpen] = useState(false);
  const [section, setSection] = useState<"create" | "library" | "history">("create");
  const [tool, setTool] = useState<Tool>(rememberedTool);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [demo, setDemo] = useState<DemoPack | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const draftRef = useRef<Draft | null>(null);
  const [assets, setAssets] = useState<Record<string, Asset>>({});
  const [results, setResults] = useState<Results>(emptyResults);
  const [records, setRecords] = useState<Draft[]>([]);
  const [library, setLibrary] = useState<LibraryEntry[]>([]);
  const [trash, setTrash] = useState(false);
  const [libraryTab, setLibraryTab] = useState<"mine" | "examples">("mine");
  const [planPane, setPlanPane] = useState<"auto" | "plan" | "results">("auto");
  const [historyTrash, setHistoryTrash] = useState(false);
  const [historyTool, setHistoryTool] = useState<"all" | Tool>("all");
  const [historyStatus, setHistoryStatus] = useState("all");
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [historyOpen, setHistoryOpen] = useState(false);
  const [inputOpen, setInputOpen] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [saveStatus, setSaveStatus] = useState("已保存");
  const [busy, setBusy] = useState(false);
  const actionLock = useRef(false);
  const [loadingDraft, setLoadingDraft] = useState(true);
  const [demoMode, setDemoMode] = useState(false);
  const [selectedDemo, setSelectedDemo] = useState<DemoItem | null>(null);
  const [selectedVersion, setSelectedVersion] = useState<Version | null>(null);
  const [selectedAsset, setSelectedAsset] = useState<Asset | null>(null);
  const [selectedWork, setSelectedWork] = useState<LibraryEntry | null>(null);
  const [editor, setEditor] = useState<Version | null>(null);
  const [picker, setPicker] = useState<"product" | "style" | "logo" | null>(null);
  const [compare, setCompare] = useState(false);
  const [compareAssetId, setCompareAssetId] = useState<string | null>(null);
  const [detailFit, setDetailFit] = useState(true);
  const [aiInstruction, setAiInstruction] = useState("");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [confirm, setConfirm] = useState<{title: string; message: string; confirmLabel?: string; run: () => Promise<void>} | null>(null);
  const [rename, setRename] = useState<{entry: LibraryEntry; value: string} | null>(null);
  const [showFacts, setShowFacts] = useState(false);
  const [showBrand, setShowBrand] = useState(false);
  const [planHistoryOpen, setPlanHistoryOpen] = useState(false);
  const [planVersions, setPlanVersions] = useState<PlanVersion[]>([]);
  const [exportOpen, setExportOpen] = useState(false);
  const [libraryUploadKind, setLibraryUploadKind] = useState<"product" | "style" | "logo">("product");
  const saveChain = useRef<Promise<unknown>>(Promise.resolve());
  const dirty = useRef(false);
  const navigation = useRef(0);
  const savedRevisions = useRef(new Map<string, number>());
  const uploadInput = useRef<HTMLInputElement>(null);
  const styleInput = useRef<HTMLInputElement>(null);
  const inputPanel = useRef<HTMLElement>(null);
  const historyPanel = useRef<HTMLElement>(null);
  usePanelFocus(inputPanel, inputOpen, () => setInputOpen(false));
  usePanelFocus(historyPanel, historyOpen, () => setHistoryOpen(false));
  const active = tools.find(item => item.id === tool)!;
  const toolConfig = catalog?.tools.find(item => item.id === tool);

  const setCurrent = useCallback((value: Draft) => {
    draftRef.current = value; dirty.current = false; savedRevisions.current.set(value.id, value.revision);
    setDraft(value); setTool(value.tool); setLoadingDraft(false); setSaveStatus("已保存"); setResults(emptyResults);
    setSelectedIds([]); setPlanPane("auto"); setCompare(false); setCompareAssetId(null); setDetailFit(true); setAiInstruction("");
    setSelectedVersion(null); setPlanHistoryOpen(false); setPlanVersions([]); setDemoMode(isRememberedDemo(value)); setError("");
    try {localStorage.setItem("studio.tool", value.tool); localStorage.setItem(`studio.draft.${value.tool}`, value.id);} catch {/* Storage may be disabled. */}
  }, []);
  const resultRequest = useRef(0);
  const refresh = useCallback(async (id: string) => {const ticket = ++resultRequest.current; const value = await studio.results(id); if (draftRef.current?.id === id && ticket === resultRequest.current) setResults(value);}, []);
  const refreshLibrary = useCallback(() => studio.library(trash).then(setLibrary).catch(value => setError(err(value))), [trash]);

  useEffect(() => {
    void studio.demos().then(setDemo).catch(value => setError(err(value)));
  }, []);
  useEffect(() => {
    if (!service.health || catalog) return;
    let live = true;
    void studio.catalog().then(value => {if (live) {setCatalog(value); setError("");}}).catch(() => {if (live) {setLoadingDraft(false); setError("创作服务未连接，请查看服务配置并重新检测。示例作品仍可浏览。");}});
    return () => {live = false;};
  }, [service.health, catalog]);
  useEffect(() => {
    if (!catalog) return;
    const ticket = ++navigation.current;
    const initialTool = rememberedTool();
    void loadToolDraft(initialTool).then(value => {if (ticket === navigation.current) setCurrent(value);}).catch(value => {if (ticket === navigation.current) {setLoadingDraft(false); setError(err(value));}});
    return () => {navigation.current++;};
  }, [catalog, setCurrent]);
  useEffect(() => {
    if (!draft) return;
    let live = true;
    const ids = [...draft.content.product_asset_ids, ...draft.content.style_asset_ids, ...(draft.content.logo_asset_id ? [draft.content.logo_asset_id] : [])];
    void Promise.all(ids.filter(id => !assets[id]).map(id => studio.asset(id))).then(values => {if (live) setAssets(old => ({...old, ...Object.fromEntries(values.map(value => [value.id, value]))}));}).catch(value => setError(err(value)));
    void refresh(draft.id).catch(value => {if (live) setError(err(value));});
    const timer = window.setInterval(() => void refresh(draft.id).catch(() => {}), 1800);
    return () => {live = false; window.clearInterval(timer);};
  }, [draft?.id, draft?.content.product_asset_ids.join(","), draft?.content.style_asset_ids.join(","), draft?.content.logo_asset_id, refresh]);
  useEffect(() => {let live = true; if (section === "library" || picker) void studio.library(picker ? false : trash).then(value => {if (live) setLibrary(value);}).catch(value => {if (live) setError(err(value));}); return () => {live = false;};}, [section, picker, trash]);
  useEffect(() => {let live = true; if (section === "history" || historyOpen) void studio.history(section === "history" && historyTrash).then(value => {if (live) setRecords(value);}).catch(value => {if (live) setError(err(value));}); return () => {live = false;};}, [section, historyOpen, historyTrash]);
  useEffect(() => {if (!notice) return; const timer = window.setTimeout(() => setNotice(""), 4500); return () => window.clearTimeout(timer);}, [notice]);
  useEffect(() => {if (!selectedVersion) return; const fresh = results.versions.find(value => value.id === selectedVersion.id); if (fresh && canonicalJson(fresh) !== canonicalJson(selectedVersion)) setSelectedVersion(fresh);}, [results.versions, selectedVersion]);
  useEffect(() => {const warn = (event: BeforeUnloadEvent) => {if (dirty.current || actionLock.current) {event.preventDefault(); event.returnValue = "";}}; window.addEventListener("beforeunload", warn); return () => window.removeEventListener("beforeunload", warn);}, []);
  useEffect(() => {const closeDrawer = (event: KeyboardEvent) => {if (event.key === "Escape" && !document.querySelector('[role="dialog"]')) {setInputOpen(false); setHistoryOpen(false);}}; window.addEventListener("keydown", closeDrawer); return () => window.removeEventListener("keydown", closeDrawer);}, []);

  function change(patch: Partial<Content>) {
    if (!draftRef.current) return;
    const next = {...draftRef.current, content: {...draftRef.current.content, ...patch}};
    draftRef.current = next; dirty.current = true; setDraft(next); setSaveStatus("未保存"); setDemoMode(false);
  }
  const persist = useCallback(async (): Promise<Draft> => {
    const current = draftRef.current;
    if (!current) throw new Error("请先建立创作草稿");
    if (!dirty.current) {await saveChain.current; return draftRef.current?.id === current.id ? draftRef.current : current;}
    const operation = saveChain.current.catch(() => {}).then(async () => {
      if (draftRef.current?.id === current.id) setSaveStatus("保存中…");
      try {
        const saved = await studio.save({...current, revision: savedRevisions.current.get(current.id) ?? current.revision});
        savedRevisions.current.set(saved.id, saved.revision);
        if (draftRef.current?.id === saved.id) {
          const untouched = draftRef.current.content === current.content;
          const next = {...draftRef.current, revision: saved.revision};
          draftRef.current = next; dirty.current = !untouched; setDraft(next); setSaveStatus(untouched ? "已保存" : "未保存");
        }
        return saved;
      } catch (value) {if (draftRef.current?.id === current.id) setSaveStatus("保存失败"); throw value;}
    });
    saveChain.current = operation;
    return operation;
  }, []);
  useEffect(() => {
    if (saveStatus !== "未保存") return;
    const timer = window.setTimeout(() => {void persist().catch(value => setError(err(value)));}, 800);
    return () => window.clearTimeout(timer);
  }, [draft?.content, saveStatus, persist]);

  async function act(action: () => Promise<void>) {
    if (actionLock.current) return;
    actionLock.current = true; setError(""); setBusy(true);
    try {await action();} catch (value) {setError(err(value));} finally {actionLock.current = false; setBusy(false);}
  }
  function navigateSection(next: "create" | "library" | "history") {
    if (actionLock.current) return;
    navigation.current++; setLoadingDraft(false); setSection(next); setHistoryOpen(false); setInputOpen(false); setSearch("");
    if (next === "library") {setTrash(false); setFilter("all"); setLibraryTab("mine");}
    if (next === "history") setHistoryTrash(false);
  }
  async function useDemo() {
    await act(async () => {if (dirty.current) await persist(); await saveChain.current; const value = await studio.create(tool, true); navigation.current++; try {localStorage.setItem(`studio.demo.${value.tool}`, canonicalJson({id: value.id, content: value.content}));} catch {/* Optional recovery preference. */} setCurrent(value); setDemoMode(true); setSection("create"); setNotice("已填入示例商品。点击“回放示例”体验流程，不会调用模型。");});
  }
  async function newCreation() {
    await act(async () => {
      if (dirty.current) await persist();
      await saveChain.current;
      const value = await studio.create(tool);
      navigation.current++; setCurrent(value); setSection("create"); setHistoryOpen(false);
      if (window.innerWidth < 1280) setInputOpen(true);
      setNotice("已新建创作，之前的内容保留在创作记录中。");
    });
  }
  async function openDraft(value: Draft) {
    const ticket = ++navigation.current;
    if (dirty.current) await persist();
    await saveChain.current;
    // Reopening the current record may follow a pending autosave; use its latest revision.
    const fresh = await studio.draft(value.id);
    if (ticket !== navigation.current) return;
    if (fresh.deleted_at) throw new Error("请先从回收站恢复此创作记录");
    setTool(fresh.tool); setCurrent(fresh); setSection("create"); setHistoryOpen(false);
  }
  async function switchTool(nextTool: Tool) {
    if (actionLock.current) return;
    const ticket = ++navigation.current;
    if (nextTool === tool && draftRef.current && !draftRef.current.deleted_at) {setLoadingDraft(false); setSection("create"); setInputOpen(false); return;}
    setLoadingDraft(true); setError("");
    try {
      if (dirty.current) await persist();
      await saveChain.current;
      const value = await loadToolDraft(nextTool);
      if (ticket !== navigation.current) return;
      setTool(nextTool); setCurrent(value); setSection("create");
      setInputOpen(false); setHistoryOpen(false);
    } catch (value) {if (ticket === navigation.current) setError(err(value));}
    finally {if (ticket === navigation.current) setLoadingDraft(false);}
  }
  async function upload(files: File[], usage: "product" | "style" | "logo", intoLibrary = false) {
    if (!files.length) return;
    await act(async () => {
      if (!intoLibrary && !draftRef.current) throw new Error("请先选择创作工具，等待草稿加载完成");
      const targetId = draftRef.current?.id;
      const max = usage === "product" ? catalog?.limits.product_references ?? 6 : usage === "style" ? catalog?.limits.style_references ?? 2 : 1;
      const existing = usage === "product" ? (draftRef.current?.content.product_asset_ids ?? []) : usage === "style" ? (draftRef.current?.content.style_asset_ids ?? []) : (draftRef.current?.content.logo_asset_id ? [draftRef.current.content.logo_asset_id] : []);
      if (!intoLibrary && (usage === "logo" ? 0 : existing.length) + files.length > max) throw new Error(`${usage === "product" ? "商品图" : usage === "style" ? "风格参考" : "Logo"}最多 ${max} 张，请减少选择`);
      if (!intoLibrary) validateReferenceCount(usage, files.length);
      const values: Asset[] = [];
      try {
        for (const file of files) {
          if (file.size > (catalog?.limits.upload_bytes ?? 25 * 1024 * 1024)) throw new Error(`“${file.name}”超过单张图片大小限制`);
          const asset = await studio.upload(file, usage); values.push(asset);
          if (intoLibrary || usage === "logo") await studio.saveLibrary(file.name, usage, {asset, images: [asset.source_url]}, [asset.id]);
        }
      } finally {
        // A later invalid file must not hide successfully uploaded earlier files.
        setAssets(old => ({...old, ...Object.fromEntries(values.map(value => [value.id, value]))}));
        if (!intoLibrary && values.length && draftRef.current?.id === targetId) {
          if (usage === "logo") change({logo_asset_id: values[0].id});
          else change({[usage === "product" ? "product_asset_ids" : "style_asset_ids"]: [...existing, ...values.map(value => value.id)]});
        }
        if (intoLibrary || usage === "logo") await refreshLibrary();
      }
    });
  }
  function validateReferenceCount(usage: "product" | "style" | "logo", added: number) {
    const content = draftRef.current?.content;
    if (!content || !catalog) return;
    const total = content.product_asset_ids.length + content.style_asset_ids.length + (content.logo_asset_id ? 1 : 0);
    if (total + added - (usage === "logo" && content.logo_asset_id ? 1 : 0) > catalog.limits.total_references) throw new Error(`商品图、风格参考和 Logo 合计最多 ${catalog.limits.total_references} 张，请先移除多余图片`);
  }
  async function chooseAsset(asset: Asset, usage: "product" | "style" | "logo") {
    const current = draftRef.current;
    if (!current) throw new Error("请先选择创作工具");
    if (asset.usage !== usage) throw new Error("用途不匹配，请选择对应的商品图、风格参考或 Logo");
    if (usage === "logo") {
      validateReferenceCount(usage, 1);
      setAssets(old => ({...old, [asset.id]: asset})); change({logo_asset_id: asset.id}); setPicker(null); setSection("create");
      return;
    }
    const key = usage === "product" ? "product_asset_ids" : "style_asset_ids";
    if (current.content[key].includes(asset.id)) {setPicker(null); setSection("create"); return;}
    if (current.content[key].length >= (usage === "product" ? catalog?.limits.product_references ?? 6 : catalog?.limits.style_references ?? 2)) throw new Error("已达到图片数量上限");
    validateReferenceCount(usage, 1);
    setAssets(old => ({...old, [asset.id]: asset})); change({[key]: [...current.content[key], asset.id]}); setPicker(null); setSection("create"); setTrash(false); setNotice("已选入当前创作");
  }
  async function chooseDemoReference(file: string, usage: "product" | "style") {
    validateReferenceCount(usage, 1);
    const count = usage === "product" ? draftRef.current?.content.product_asset_ids.length : draftRef.current?.content.style_asset_ids.length;
    const maximum = usage === "product" ? catalog?.limits.product_references ?? 6 : catalog?.limits.style_references ?? 2;
    if ((count ?? 0) >= maximum) throw new Error("已达到图片数量上限，请先移除多余图片");
    const blob = await fetch(demoUrl(file)).then(response => response.blob());
    const asset = await studio.upload(new File([blob], file, {type: blob.type}), usage);
    await chooseAsset(asset, usage);
  }
  async function queueOrRun(action: () => Promise<void>) {
    await act(async () => {
      const health = await service.refresh();
        if (!health || (!health.generation_available && !health.generation_submission_available)) {setServiceOpen(true); return;}
        if (!health.generation_available && health.generation_provider === "azure") {setServiceOpen(true); return;}
      if (!health.generation_available) {
        setConfirm({title: "当前只能加入待执行队列", message: "自动生图执行器尚未接入。本次只保存任务，不会立即调用模型或自动出图；需要执行人员手动处理。也可以取消并继续编辑草稿。", confirmLabel: "仅加入队列", run: action});
        return;
      }
      await action();
    });
  }
  async function generate(pageIds?: string[], source?: Version) {
    const submit = async () => {
      const saved = await persist();
      if (source && catalog) {
        const content = saved.content;
        if (content.product_asset_ids.length + content.style_asset_ids.length + (content.logo_asset_id ? 1 : 0) + 1 > catalog.limits.total_references) throw new Error("AI 修改需要为当前底图预留一张参考图位置，请先移除一张可选参考图");
      }
      const options = {mode: demoMode && !source ? "demo" : "codex", page_ids: pageIds, ...(source ? {source_version_id: source.id, instruction: aiInstruction} : {})};
      const fingerprint = canonicalJson({draft_id: saved.id, content: saved.content, options});
      const key = `studio.submission.${saved.id}`;
      let attempt = {fingerprint, draft: saved, options: {...options, submit_key: newKey()}};
      // Keep an unacknowledged request across retries/reloads. Its revision is part
      // of the server's idempotency contract and must not be silently refreshed.
      try {const previous = JSON.parse(sessionStorage.getItem(key) ?? "null"); if (previous?.fingerprint === fingerprint) attempt = previous; sessionStorage.setItem(key, JSON.stringify(attempt));} catch {/* A disabled store only affects reload recovery. */}
      await studio.generate(attempt.draft, attempt.options);
      try {sessionStorage.removeItem(key);} catch {/* Optional recovery state. */}
      setSelectedVersion(null); setSelectedIds([]); setPlanPane("results"); setAiInstruction(""); setInputOpen(false); await refresh(saved.id);
      if (!demoMode || source) setNotice("任务已保存。请查看下方执行状态；等待执行的任务尚未开始出图。");
    };
    if (demoMode && !source) await act(submit);
    else await queueOrRun(submit);
  }
  async function requestPlan() {
    await act(async () => {
      const health = await service.refresh();
      if (!health?.planning_available) {setServiceOpen(true); return;}
      setConfirm({title: "重新生成 A+ 模块方案？", message: "将根据当前商品名称、制作要求和已填写的事实文本生成新方案。商品图片不会参与本次规划，也不会在此步骤生成图片。", run: planAPlus});
    });
  }
  async function planAPlus() {
      const saved = await persist();
      const planned = await studio.plan(saved);
      setCurrent(planned); setPlanPane("plan");
      setDemoMode(false);
      await refresh(planned.id);
      setPlanVersions(await studio.plans(planned.id));
      setNotice("已生成新的 A+ 模块方案；请确认文案和画面描述后再生成图片。");
  }
  async function togglePlanHistory() {
    if (!draft) return;
    if (!planHistoryOpen) setPlanVersions(await studio.plans(draft.id));
    setPlanHistoryOpen(!planHistoryOpen);
  }
  async function restorePlan(plan: PlanVersion) {
    if (!draft) return;
    const saved = await persist();
    const restored = await studio.restorePlan(saved, plan.id);
    setCurrent(restored); setPlanPane("plan"); setDemoMode(false); await refresh(restored.id); setPlanVersions(await studio.plans(restored.id));
    setNotice(`已恢复方案：${plan.label}。此操作未生成图片。`);
  }
  async function saveWork(versions: Version[]) {
    if (!draft || !versions.length) return;
    if (dirty.current) await persist();
    const ids = new Set([...draft.content.product_asset_ids, ...draft.content.style_asset_ids, ...(draft.content.logo_asset_id ? [draft.content.logo_asset_id] : []), ...versions.flatMap(value => [value.base_asset_id, value.render_asset_id, ...value.layers.flatMap(layer => layer.asset_id ? [layer.asset_id] : [])])]);
    const result = await studio.saveLibrary(`${draft.content.product_name.slice(0, 180) || "商品创作"} · ${versions.length > 1 ? `${versions.length} 张套图` : "精选"}`, "work", {versions, content: structuredClone(draft.content), images: versions.map(value => value.image_url)}, [...ids]);
    setNotice(result.already_saved ? "这组版本已经在素材库中了" : "已加入素材库，保存为独立作品快照");
  }
  async function continueLibraryWork(entry: LibraryEntry) {
    await act(async () => {
      if (dirty.current) await persist();
      await saveChain.current;
      const copied = await studio.continueWork(entry.id);
      navigation.current++;
      setTool(copied.draft.tool); setCurrent(copied.draft); setResults(copied.results); setSection("create");
      setNotice("已从收藏快照建立独立创作副本；后续修改不会覆盖原收藏。");
    });
  }
  async function saveStylePreset() {
    if (!draft) return;
    const styleNames: Record<string, string> = {auto: "自动匹配", minimal: "简约", home: "居家", technology: "科技", premium: "高端", promotion: "促销"};
    const ids = draft.content.style_asset_ids;
    const images = ids.flatMap(id => assets[id]?.preview_url ? [assets[id].preview_url] : []);
    const result = await studio.saveLibrary(
      `${styleNames[draft.content.style] ?? "自定义"}风格预设`, "style_preset",
      {style: draft.content.style, style_asset_ids: ids, brand_color: draft.content.brand_color, brand_font: draft.content.brand_font, images}, ids,
    );
    setNotice(result.already_saved ? "这个风格预设已经保存过了" : "风格预设已保存，可在素材库中应用或改名");
  }
  function applyStylePreset(entry: LibraryEntry) {
    if (!draft) throw new Error("请先进入一个创作工具");
    const allowed = ["auto", "minimal", "home", "technology", "premium", "promotion"];
    const style = String(entry.payload.style ?? "");
    const ids = Array.isArray(entry.payload.style_asset_ids) ? entry.payload.style_asset_ids.filter(value => typeof value === "string") as string[] : [];
    if (!allowed.includes(style) || ids.length > 2) throw new Error("风格预设数据无效")
    if (catalog && draft.content.product_asset_ids.length + ids.length + (draft.content.logo_asset_id ? 1 : 0) > catalog.limits.total_references) throw new Error(`应用此预设会超过 ${catalog.limits.total_references} 张参考图上限，请先移除多余图片`);
    const color = typeof entry.payload.brand_color === "string" && /^#[0-9a-f]{6}$/i.test(entry.payload.brand_color) ? entry.payload.brand_color : "";
    const font = ["auto", "sans", "serif", "wenkai"].includes(String(entry.payload.brand_font)) ? String(entry.payload.brand_font) : "auto";
    change({style: style as Content["style"], style_asset_ids: ids, brand_color: color, brand_font: font});
    setSection("create"); setNotice("已应用风格预设；商品、事实、文案和图片尺寸保持不变。点击生成后才会调用 AI。");
  }
  async function download(url: string, filename: string) {
    const response = await fetch(mediaUrl(url)); if (!response.ok) throw new Error("图片文件暂不可读取");
    const href = URL.createObjectURL(await response.blob()); const anchor = document.createElement("a"); anchor.href = href; anchor.download = filename; anchor.click(); window.setTimeout(() => URL.revokeObjectURL(href), 3000);
  }
  const showPlan = tool === "a_plus_detail" && (planPane === "plan" || (planPane === "auto" && !results.versions.length));
  const activePages = (draft?.content.pages ?? []).filter(page => !page.skipped);
  const currentVersions = activePages.flatMap(page => {const selected = results.selections.find(value => value.page_id === page.id); const version = results.versions.find(value => value.id === selected?.version_id); return version ? [version] : [];});
  const latestVersionIds = new Set(results.operations[0]?.jobs.flatMap(job => job.version_id ? [job.version_id] : []) ?? []);
  const pagePositions = new Map((draft?.content.pages ?? []).map((page, index) => [page.id, index]));
  const candidatePositions = new Map(results.operations.flatMap(operation => operation.jobs.flatMap(job => job.version_id ? [[job.version_id, job.variant] as const] : [])));
  const visibleVersions = results.versions
    .filter(version => activePages.some(page => page.id === version.page_id) && (latestVersionIds.has(version.id) || currentVersions.some(current => current.id === version.id)))
    .sort((left, right) => (pagePositions.get(left.page_id) ?? 999) - (pagePositions.get(right.page_id) ?? 999) || (candidatePositions.get(left.id) ?? 999) - (candidatePositions.get(right.id) ?? 999) || left.created_at.localeCompare(right.created_at));
  const pickedVersions = selectedIds.length ? visibleVersions.filter(value => selectedIds.includes(value.id)) : currentVersions;
  useEffect(() => {const visible = new Set(visibleVersions.map(value => value.id)); setSelectedIds(ids => ids.some(id => !visible.has(id)) ? ids.filter(id => visible.has(id)) : ids);}, [visibleVersions.map(value => value.id).join(",")]);
  const allJobs = results.operations.flatMap(value => value.jobs);
  const pending = allJobs.filter(value => ["queued", "running"].includes(value.status));
  const runningCount = pending.filter(job => job.status === "running").length;
  const queuedCount = pending.length - runningCount;
  const retryable = results.operations.filter(operation => !operation.stopped).flatMap(operation => operation.jobs).filter(job => job.status === "failed");
  const compareReferenceId = draft?.content.product_asset_ids.includes(compareAssetId ?? "") ? compareAssetId : draft?.content.product_asset_ids[0];
  const aPlusReady = tool !== "a_plus_detail" || Boolean(activePages.length && activePages.every(page => (page.title.trim() || page.body.trim()) && page.visual_goal.trim()));
  const settingsChanged = Boolean(draft && results.operations[0] && canonicalJson(results.operations[0].snapshot.content) !== canonicalJson(draft.content));
  const selectedReviewTask = selectedVersion ? [...results.review_tasks].reverse().find(value => value.version_id === selectedVersion.id) : undefined;
  const cardImage = (entry: LibraryEntry) => entry.payload.images?.[0] ?? entry.payload.asset?.preview_url ?? (entry.payload.demo ? demoUrl(entry.payload.demo.file) : "");
  const exportRows = pickedVersions.map((version, index) => {const page = activePages.find(value => value.id === version.page_id); const label = toolConfig?.purposes.find(value => value.id === page?.purpose)?.label ?? "作品"; return {version, filename: `${String(index + 1).padStart(2, "0")}-${label.replace(/[\\/:*?"<>|]/g, "-")}`};});
  const missingExportPages = Math.max(0, activePages.length - currentVersions.length);
  const filteredLibrary = library.filter(entry => (filter === "all" || entry.kind === filter) && entry.name.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()));
  async function trashDraft(value: Draft) {
    if (draftRef.current?.id === value.id) {if (dirty.current) await persist(); await saveChain.current;}
    await studio.draftAction(value.id, "trash");
    if (draftRef.current?.id === value.id) {
      navigation.current++; draftRef.current = null; dirty.current = false; setDraft(null); setResults(emptyResults); setSelectedVersion(null); setSelectedIds([]); setDemoMode(false);
    }
    setRecords(await studio.history());
  }

  function demoCards(items: DemoItem[], compact = false) {
    return <div className={`st-gallery ${compact ? "compact" : ""}`}>{items.map(item => <article className="st-art-card" key={item.id}>
      <button className="st-art-image" onClick={() => setSelectedDemo(item)} aria-label={`查看${item.title}`}><img src={demoUrl(item.file)} alt={item.title}/><span className="st-image-label">示例作品</span><span className="st-image-hover"><Icon name="image"/> 查看作品</span></button>
      <div className="st-art-info"><strong>{item.title}</strong><span>{item.subtitle}</span><div className="st-tags">{item.tags.slice(0, 2).map(tag => <small key={tag}>{tag}</small>)}<em>{item.width} × {item.height}</em></div></div>
    </article>)}</div>;
  }
  function historyCards() {
    const trashView = section === "history" && historyTrash;
    const visibleRecords = records.filter(value => section !== "history" || ((historyTool === "all" || value.tool === historyTool) && (historyStatus === "all" || value.history_status === historyStatus) && (value.content.product_name + tools.find(t => t.id === value.tool)?.name).toLocaleLowerCase().includes(search.trim().toLocaleLowerCase())));
    if (!visibleRecords.length) return <div className="st-empty-small"><p>{search || historyTool !== "all" || historyStatus !== "all" ? "没有匹配的创作记录，请调整搜索或筛选条件。" : trashView ? "回收站是空的" : "还没有创作记录"}</p></div>;
    return visibleRecords.map(value => <article className="st-history-item" key={value.id}><button className="st-history-open" disabled={trashView} onClick={() => void act(() => openDraft(value))}><span className={`st-history-icon ${value.thumbnail_url ? "has-image" : ""}`}>{value.thumbnail_url ? <img src={mediaUrl(value.thumbnail_url)} alt=""/> : <Icon name={tools.find(t => t.id === value.tool)?.icon ?? "image"}/>}</span><span><strong>{value.content.product_name || "未命名创作"}</strong><small>{tools.find(t => t.id === value.tool)?.name} · {new Date(value.updated_at).toLocaleString("zh-CN", {month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit"})}</small>{value.history_status && <em className={`st-history-status ${value.history_status}`}>{historyStatusLabels[value.history_status]}{value.result_count ? ` · ${value.result_count} 个版本` : ""}</em>}{value.expires_at && <small>保留至 {new Date(value.expires_at).toLocaleDateString("zh-CN")}</small>}</span>{!trashView && <span className="st-history-continue">继续创作 <Icon name="chevron" size={16}/></span>}</button><div className="st-history-actions">{trashView ? <><button onClick={() => void act(async () => {await studio.draftAction(value.id, "restore"); setRecords(await studio.history(true)); setNotice("已恢复创作记录");})}>恢复</button><button className="danger" onClick={() => setConfirm({title: "彻底删除此创作记录？", message: "此操作无法恢复。已收藏的独立作品不受影响；在途或结果不明任务会阻止删除。", run: async () => {await studio.draftAction(value.id, "purge"); setRecords(await studio.history(true));}})}>彻底删除</button></> : <ActionMenu label={`更多操作：${value.content.product_name || "未命名创作"}`}><button role="menuitem" className="danger" aria-label={`删除${value.content.product_name || "未命名创作"}`} onClick={() => setConfirm({title: "将创作记录移入回收站？", message: "未发出的后续任务会停止，已有结果保留 30 天。已收藏的独立作品不受影响。", run: async () => {await trashDraft(value);}})}><Icon name="trash" size={15}/>移入回收站</button></ActionMenu>}</div></article>);
  }
  if (editor) return <Editor version={editor} onClose={() => setEditor(null)} onApplied={value => {setEditor(null); setSelectedVersion(value); if (draft) void refresh(draft.id); setNotice("已完成手动编辑；未调用 AI 或质检");}}/>;

  return <div className="st-app" aria-busy={busy || loadingDraft}>
    <aside className="st-nav"><a className="st-brand" href="#" onClick={event => {event.preventDefault(); navigateSection("create");}}><span className="st-mark"><Icon name="spark" size={22}/></span><span>商品创作<small>CONTENT STUDIO</small></span></a>
      <span className="st-nav-caption">AI 创作工具</span><nav>{tools.map(item => <button key={item.id} aria-label={item.name} title={item.name} disabled={busy} className={section === "create" && tool === item.id ? "active" : ""} onClick={() => void switchTool(item.id)}><Icon name={item.icon}/><span>{item.name}</span></button>)}</nav>
      <span className="st-nav-caption st-divider">我的空间</span><nav><button className={section === "library" ? "active" : ""} aria-label="素材库" title="素材库" disabled={busy} onClick={() => navigateSection("library")}><Icon name="folder"/><span>素材库</span></button><button className={section === "history" ? "active" : ""} aria-label="创作记录" title="创作记录" disabled={busy} onClick={() => navigateSection("history")}><Icon name="history"/><span>创作记录</span></button></nav>
    </aside>
    <div className="st-main" inert={busy}><header className="st-top"><div><span className="st-breadcrumb">工作空间</span><Icon name="chevron" size={14}/><strong>{section === "create" ? active.name : section === "library" ? "素材库" : "创作记录"}</strong></div><div><button className="st-link st-service-trigger" onClick={() => setServiceOpen(true)}><span className={`st-service-dot ${service.connection === "offline" ? "offline" : service.health?.generation_available ? "ready" : "pending"}`}/>{service.connection === "offline" ? "服务断开" : "服务配置"}</button><span className="st-top-separator"/><button className="st-link" onClick={() => setNotice("预置作品仅用于演示和效果参考；自定义内容需重新提交生成。")}>演示说明 <Icon name="info" size={15}/></button></div></header>
      <ServiceBanner service={service} onConfigure={() => setServiceOpen(true)}/>
      {error && <div className="st-alert" role="alert"><Icon name="info" size={18}/><span>{error}</span><button className="st-icon" aria-label="关闭提示" onClick={() => setError("")}><Icon name="close" size={16}/></button></div>}
      {section === "create" ? <div className="st-workspace" inert={loadingDraft}>{inputOpen && <button className="st-input-backdrop" aria-label="收起创作设置" tabIndex={-1} onClick={() => setInputOpen(false)}/>}
        <aside ref={inputPanel} aria-label="创作设置面板" className={`st-input ${inputOpen ? "open" : ""}`}><div className="st-input-heading"><button className="st-icon st-input-close" aria-label="关闭创作设置" onClick={() => setInputOpen(false)}><Icon name="close"/></button><h1>{active.name}</h1><p>{active.description}</p></div>
          <div className="st-input-scroll" onPaste={event => {const files = Array.from(event.clipboardData.files); if (files.length) {event.preventDefault(); void upload(files, "product");}}}>
            <h2 className="st-settings-section">商品资料</h2><div className="st-field-title"><label>商品图片 <b>*</b></label><span>{draft?.content.product_asset_ids.length ?? 0}/6</span></div>
            <div className="st-upload" onDragOver={event => event.preventDefault()} onDrop={event => {event.preventDefault(); void upload(Array.from(event.dataTransfer.files), "product");}}>
              {draft?.content.product_asset_ids.length ? <div className="st-ref-grid">{draft.content.product_asset_ids.map((id, index) => <div key={id}><img src={mediaUrl(assets[id]?.preview_url ?? "")} alt={`商品参考 ${index + 1}`}/><small>{index === 0 ? "主参考" : `参考 ${index + 1}`}</small><button className="st-ref-remove" aria-label={`移除商品参考 ${index + 1}`} onClick={() => change({product_asset_ids: draft.content.product_asset_ids.filter(value => value !== id)})}>×</button>{draft.content.product_asset_ids.length > 1 && <div className="st-ref-order"><button aria-label={`前移商品参考 ${index + 1}`} disabled={index === 0} onClick={() => {const ids = [...draft.content.product_asset_ids]; [ids[index - 1], ids[index]] = [ids[index], ids[index - 1]]; change({product_asset_ids: ids});}}>←</button><button aria-label={`后移商品参考 ${index + 1}`} disabled={index === draft.content.product_asset_ids.length - 1} onClick={() => {const ids = [...draft.content.product_asset_ids]; [ids[index + 1], ids[index]] = [ids[index], ids[index + 1]]; change({product_asset_ids: ids});}}>→</button></div>}</div>)}<button className="st-add-ref" aria-label="继续上传商品图" onClick={() => uploadInput.current?.click()}><Icon name="plus"/></button></div> : <button className="st-upload-empty" onClick={() => uploadInput.current?.click()}><span><Icon name="upload" size={25}/></span><strong>点击或拖拽上传商品图</strong><small>也可直接粘贴图片</small></button>}
              <input hidden ref={uploadInput} type="file" accept="image/png,image/jpeg,image/webp" multiple onChange={event => {void upload(Array.from(event.target.files ?? []), "product"); event.target.value = "";}}/>
            </div><div className="st-upload-bottom"><small>PNG / JPG / WebP · 单张 ≤ 25 MB</small><button className="st-link" onClick={() => setPicker("product")}>素材库选择</button></div>
            <label className="st-field">商品名称 <small>选填</small><input maxLength={200} placeholder="例如：深色滚筒洗衣机" value={draft?.content.product_name ?? ""} onChange={event => change({product_name: event.target.value})}/></label>
            <h2 className="st-settings-section">创作要求</h2><label className="st-field">制作要求 <small>选填</small><textarea maxLength={16000} placeholder={tool === "scene_image" ? "描述想要的空间、光线和氛围…" : "描述想表达的卖点、文案或画面风格…"} rows={4} value={draft?.content.requirements ?? ""} onChange={event => change({requirements: event.target.value})}/></label>
            <button className="st-disclosure" aria-expanded={showFacts} onClick={() => setShowFacts(!showFacts)}>商品事实与来源 <span>{showFacts ? "收起" : "展开"}</span></button>
            {showFacts && <div className="st-facts"><p>尺寸、型号、认证等内容需要明确依据；不从风格参考推断。未填完的行会保存为草稿，但不会提交给 AI。</p><div className="st-product-meta"><input maxLength={200} aria-label="SKU" placeholder="SKU（选填）" value={draft?.content.sku ?? ""} onChange={event => change({sku: event.target.value})}/><input maxLength={200} aria-label="商品品类" placeholder="品类（选填）" value={draft?.content.category ?? ""} onChange={event => change({category: event.target.value})}/></div>{draft?.content.facts.map((fact, index) => <div key={index}>{(["name", "value", "source"] as const).map(key => <input key={key} aria-label={`事实 ${index + 1} ${key}`} placeholder={{name: "字段，如容量", value: "实际值", source: "来源，如规格书第 2 页"}[key]} value={fact[key]} onChange={event => change({facts: draft.content.facts.map((row, i) => i === index ? {...row, [key]: event.target.value} : row)})}/>)}<button className="st-link danger" onClick={() => change({facts: draft.content.facts.filter((_, i) => i !== index)})}>删除</button></div>)}<button className="st-secondary small" onClick={() => draft && change({facts: [...draft.content.facts, {name: "", value: "", source: ""}]})}>添加事实</button></div>}
            <div className="st-field-title"><label>画面风格</label><button className="st-link" onClick={() => setPicker("style")}>参考图 {draft?.content.style_asset_ids.length ? `(${draft.content.style_asset_ids.length})` : "+"}</button></div>
            <div className="st-style-options">{[["auto", "自动匹配"], ["minimal", "简约"], ["home", "居家"], ["technology", "科技"], ["premium", "高端"], ["promotion", "促销"]].map(([value, label]) => <button key={value} className={draft?.content.style === value ? "active" : ""} onClick={() => change({style: value})}>{label}</button>)}</div><button className="st-link st-save-style" onClick={() => void act(saveStylePreset)}><Icon name="folder" size={15}/>保存为风格预设</button>
            {!!draft?.content.style_asset_ids.length && <div className="st-style-refs">{draft.content.style_asset_ids.map(id => <button key={id} title="点击移除风格参考" onClick={() => change({style_asset_ids: draft.content.style_asset_ids.filter(value => value !== id)})}><img src={mediaUrl(assets[id]?.preview_url ?? "")} alt="风格参考"/><span>×</span></button>)}</div>}
            <button className="st-disclosure st-brand-disclosure" aria-expanded={showBrand} onClick={() => setShowBrand(!showBrand)}>品牌偏好 <span>{showBrand ? "收起" : "展开"}</span></button>
            {showBrand && <div className="st-brand-settings"><p>用于约束 AI 生成的主色、字体气质和 Logo。不指定时由系统按画面自动匹配。</p><div className="st-brand-row"><label>品牌主色</label><input aria-label="品牌主色" type="color" value={draft?.content.brand_color || "#635bff"} onChange={event => change({brand_color: event.target.value})}/><code>{draft?.content.brand_color || "未指定"}</code>{draft?.content.brand_color && <button className="st-link" onClick={() => change({brand_color: ""})}>清除</button>}</div><label className="st-field">字体气质<select value={draft?.content.brand_font ?? "auto"} onChange={event => change({brand_font: event.target.value as Content["brand_font"]})}><option value="auto">自动匹配</option><option value="sans">现代无衬线</option><option value="serif">精致衬线</option><option value="wenkai">亲和楷体</option></select></label><div className="st-brand-logo"><div><span>Logo</span><small>从素材库选择，不会从参考图自动提取</small></div>{draft?.content.logo_asset_id ? <button className="st-logo-preview" title="点击移除 Logo" onClick={() => change({logo_asset_id: null})}><img src={mediaUrl(assets[draft.content.logo_asset_id]?.preview_url ?? "")} alt="已选 Logo"/><span>×</span></button> : <button className="st-secondary small" onClick={() => setPicker("logo")}>选择 Logo</button>}</div></div>}
            <h2 className="st-settings-section">输出设置</h2><label className="st-field">输出语言<select value={draft?.content.market ?? "domestic_zh"} onChange={event => change({market: event.target.value})}><option value="domestic_zh">国内电商 · 中文</option><option value="amazon_en">Amazon · English</option></select></label>
            <label className="st-field">图片文字<select value={draft?.content.text_mode ?? "native"} onChange={event => change({text_mode: event.target.value})}><option value="native">图文一起生成</option><option value="background_only">只生成底图（保留商品标识）</option></select></label>
            <div className="st-field-title"><label>图片尺寸</label><span>生成前配置</span></div><div className="st-size-row"><select aria-label="图片比例" value={draft?.content.output.ratio ?? "1:1"} onChange={event => draft && change({output: {...draft.content.output, ratio: event.target.value}})}>{["1:1", "3:4", "4:3", "2:3", "3:2", "16:9", "9:16"].map(value => <option key={value}>{value}</option>)}</select><select aria-label="分辨率" value={draft?.content.output.resolution ?? "2k"} onChange={event => draft && change({output: {...draft.content.output, resolution: event.target.value}})}><option value="2k">高清 · 约 2K</option><option value="1k">标准 · 约 1K</option></select></div><small className="st-size-note">{(() => {const size = catalog?.sizes.find(row => row.ratio === draft?.content.output.ratio && row.resolution === draft?.content.output.resolution); return size ? `${size.width} × ${size.height} px · High` : "加载配置中";})()}</small>
            <div className="st-field-title"><label>{(draft?.content.pages.length ?? 0) > 1 ? "每页候选数" : "候选数量"}</label></div><div className="st-segment">{[1, 2, 4].map(count => <button key={count} className={draft?.content.candidate_count === count ? "active" : ""} onClick={() => change({candidate_count: count})}>{count} 张</button>)}</div>
            {demo && <button className="st-example-fill" onClick={() => void useDemo()}><Icon name="spark" size={18}/><span>没有素材？试用示例商品</span><Icon name="chevron" size={15}/></button>}
          </div>
          <div className="st-generate-footer"><div><span>{loadingDraft ? "加载草稿中…" : saveStatus}{saveStatus === "保存失败" && <button className="st-link" onClick={() => void act(async () => {await persist();})}>重试保存</button>}</span></div><p className="st-generation-summary">{activePages.length} 张图片 · 每张 {draft?.content.candidate_count ?? 1} 候选 · {draft?.content.output.resolution.toUpperCase()}</p><button className="st-primary" disabled={!draft || busy || loadingDraft || !draft.content.product_asset_ids.length || !activePages.length || !aPlusReady || service.connection !== "online"} onClick={() => void generate()}><Icon name={demoMode ? "image" : "spark"}/>{busy ? "提交中…" : demoMode ? "回放示例" : "开始生成"}</button><small>{!aPlusReady ? "请先生成模块方案，或填写每个模块的文案与画面描述" : demoMode ? "使用预置 AI 成图，实际像素以示例为准" : !service.health?.generation_available ? "尚未连接自动生图服务；提交前需确认仅排队" : "生成后可在创作记录中查看进度"}</small></div>
        </aside>
        <main className="st-results"><div className="st-results-heading"><div><h2>{results.versions.length || allJobs.length ? "创作结果" : "开始你的下一次创作"}</h2><p>{results.versions.length || allJobs.length ? "每张候选独立完成，可分别查看、选用或重试" : "上传商品图片，余下的交给你的创作工作台"}</p></div><div className="st-toolbar"><button className="st-secondary" disabled={busy || loadingDraft} onClick={() => void newCreation()}><Icon name="plus" size={17}/>新建创作</button><button className="st-secondary st-input-toggle" onClick={() => setInputOpen(!inputOpen)}>创作设置</button><button className="st-secondary" onClick={() => setHistoryOpen(!historyOpen)}><Icon name="history" size={17}/>创作记录</button></div></div>
          {tool === "a_plus_detail" && <div className="st-workflow-tabs" aria-label="A+ 创作阶段"><button className={showPlan ? "active" : ""} aria-pressed={showPlan} onClick={() => setPlanPane("plan")}>编辑方案与模块</button><button className={!showPlan ? "active" : ""} aria-pressed={!showPlan} onClick={() => setPlanPane("results")}>查看结果 {results.versions.length ? `(${results.versions.length})` : ""}</button></div>}
          {(tool === "ecom_suite" || showPlan) && draft && <PagePurposes key={draft.id} content={draft.content} config={toolConfig} sizes={catalog?.sizes ?? []} onChange={pages => change({pages})}/>}
          {showPlan && draft && <section className="st-plan"><div className="st-section-line"><div><strong>A+ 模块方案</strong><p>先规划，再生成；文案与画面描述都可以修改。</p></div><div className="st-plan-actions"><button className="st-secondary" onClick={() => void act(togglePlanHistory)}><Icon name="history" size={16}/>方案版本</button><button className="st-secondary" disabled={busy} onClick={() => void requestPlan()}><Icon name="spark" size={16}/>智能生成方案</button></div></div>{planHistoryOpen && <div className="st-plan-history">{planVersions.length ? planVersions.map(plan => <div key={plan.id}><span><strong>{plan.label}</strong><small>{new Date(plan.created_at).toLocaleString("zh-CN")}</small></span><button className="st-link" onClick={() => setConfirm({title: "恢复这个模块方案？", message: "当前模块文案和顺序会被替换，恢复前的方案仍会保留在版本中。不会触发生图。", run: async () => restorePlan(plan)})}>恢复</button></div>) : <p>尚无方案版本。首次智能重新规划后开始保留。</p>}</div>}<PlanEditor key={draft.id} content={draft.content} config={toolConfig} onChange={pages => change({pages})}/></section>}
          {settingsChanged && !!results.versions.length && <div className="st-settings-changed"><Icon name="info" size={17}/><span>当前设置已修改，已有图片不会自动变化。重新生成后才会应用新设置。</span></div>}
          {!!pending.length && <div className="st-progress"><span className={runningCount ? "st-spinner" : "st-queued-dot"}/><div><strong>{service.connection === "offline" ? "服务断开，任务状态暂未更新" : runningCount ? results.operations[0]?.mode === "demo" ? "正在回放示例" : "正在生成" : "等待执行"}</strong><small>已完成 {allJobs.filter(j => j.status === "done").length} 张 · 执行中 {runningCount} 项 · 排队 {queuedCount} 项。{service.connection === "offline" ? "请恢复服务后重新检测。" : !runningCount && !service.health?.generation_available ? "尚无自动执行器，需要手动处理。" : "离开页面不丢记录。"}</small></div><button className="st-link" onClick={() => setServiceOpen(true)}>查看服务配置</button><button className="st-link" onClick={() => void act(async () => {for (const operation of results.operations.filter(op => !op.stopped)) await studio.stop(operation.id); if (draft) await refresh(draft.id);})}>停止后续生成</button></div>}
          {!!pending.length && <div className="st-gallery st-pending-grid">{pending.map(job => <article className="st-pending-card" key={job.id}><div><span className={job.status === "running" ? "st-spinner" : "st-queued-dot"}/><strong>{toolConfig?.purposes.find(item => item.id === draft?.content.pages.find(page => page.id === job.page_id)?.purpose)?.label ?? "图片"} · 候选 {job.variant}</strong><small>{job.status === "running" ? "正在生成" : "等待生成"}</small></div></article>)}</div>}
          {!showPlan && !!results.versions.length && <><div className="st-result-actions"><div><strong>共 {visibleVersions.length} 张 · 已勾选 {selectedIds.length} 张</strong><small>{selectedIds.length ? "批量操作将使用勾选的图片" : `未勾选时，导出与收藏使用 ${currentVersions.length} 张当前选用版本`}</small></div><div className="st-result-tools">{selectedIds.length > 0 && <button className="st-link" onClick={() => setSelectedIds([])}>清空勾选</button>}<button className="st-secondary small" onClick={() => setExportOpen(true)}><Icon name="download" size={16}/>导出</button><button className="st-secondary small" onClick={() => void act(() => saveWork(pickedVersions))}><Icon name="folder" size={16}/>加入素材库</button></div></div><div className="st-gallery st-result-grid">{visibleVersions.map(version => <article className="st-art-card" key={version.id}><div className="st-art-image"><button className="st-image-button" aria-label="查看图片详情" onClick={() => {setSelectedVersion(version); setCompare(false); setCompareAssetId(draft?.content.product_asset_ids[0] ?? null); setDetailFit(true);}}><VersionVisual version={version} alt="生成结果"/></button><label className="st-card-check"><input type="checkbox" aria-label="勾选图片用于批量操作" checked={selectedIds.includes(version.id)} onChange={event => setSelectedIds(ids => event.target.checked ? [...ids, version.id] : ids.filter(id => id !== version.id))}/></label>{currentVersions.some(value => value.id === version.id) && <span className="st-current-selection"><Icon name="check" size={14}/>当前选用</span>}<span className="st-image-label">{version.kind === "manual" ? "已手动编辑" : version.provenance.provider.includes("demo") ? "示例回放" : version.kind === "repair" ? "AI 修复" : "AI 生成"}</span></div><div className="st-art-info"><div className="st-card-title"><strong>{toolConfig?.purposes.find(p => p.id === draft?.content.pages.find(page => page.id === version.page_id)?.purpose)?.label ?? "图片"}</strong><span className="st-score">{version.kind === "manual" ? "手动编辑" : version.review.score != null ? `${version.review.score} 分` : "检查未完成"}</span></div><p className="st-card-meta">{version.width} × {version.height} px · {version.kind === "manual" ? "手动编辑版" : "AI 成图"}</p><div className="st-card-buttons"><button onClick={() => setEditor(version)}><Icon name="edit" size={16}/>编辑</button><button onClick={() => void act(() => downloadVersion(version, `商品图-${version.id.slice(0, 6)}`, "png"))}><Icon name="download" size={16}/>下载</button><button aria-label="重新生成这一页" onClick={() => void generate([version.page_id])}><Icon name="spark" size={16}/>重新生成</button></div></div></article>)}</div></>}
          {!!retryable.length && <div className="st-retry-all"><span>{retryable.length} 个候选已确认生成失败，其他成功结果不会重做。</span><button className="st-secondary small" onClick={() => void queueOrRun(async () => {for (const job of retryable) await studio.retry(job.id); if (draft) await refresh(draft.id);})}>补生成失败项</button></div>}
          {allJobs.filter(job => ["failed", "unknown", "stopped"].includes(job.status)).map(job => <div className="st-job-error" key={job.id}><Icon name="info"/><div><strong>{statusLabels[job.status]}</strong><p>{job.error || "保留已经完成的图片，不再派发后续请求。"}</p></div>{retryable.some(value => value.id === job.id) && <button className="st-secondary" onClick={() => void queueOrRun(async () => {await studio.retry(job.id); if (draft) await refresh(draft.id);})}>重试此项</button>}</div>)}
          {!results.versions.length && !allJobs.length && <section className="st-welcome"><div className="st-welcome-copy"><span className="st-eyebrow">FROM PRODUCT TO CONTENT</span><h3>一张商品图，<br/>更多种表达。</h3><p>主图、场景、卖点与完整套图。<br/>从可直接浏览的作品开始，找到你的创作方向。</p><button className="st-primary" onClick={() => navigateSection("library")}>浏览素材库 <Icon name="arrow" size={18}/></button></div><div className="st-welcome-art">{demo?.items.slice(0, 2).map((item, index) => <button key={item.id} className={`art-${index}`} onClick={() => setSelectedDemo(item)}><img src={demoUrl(item.file)} alt={item.title}/></button>)}<span className="st-welcome-tag"><Icon name="check" size={14}/> 平台示例</span></div></section>}
          {!showPlan && demo && <details className="st-inspiration" key={results.versions.length ? "has-results" : "empty"} open={!results.versions.length}><summary>灵感与示例作品 <span>展开查看平台示例</span></summary><section><div className="st-section-line"><div><h3>灵感与示例作品</h3><p>无需生成，即可查看完整效果</p></div><button className="st-link" onClick={() => navigateSection("library")}>全部素材 <Icon name="arrow" size={16}/></button></div>{demoCards(demo.items.slice(0, 3), true)}</section></details>}
        </main>
        {historyOpen && <aside ref={historyPanel} aria-label="创作记录面板" className="st-history-drawer"><div className="st-section-line"><h3>创作记录</h3><button className="st-icon" aria-label="收起记录" onClick={() => setHistoryOpen(false)}><Icon name="close"/></button></div>{historyCards()}<p className="st-muted">只展示真实创建的草稿和任务。</p></aside>}
      </div> : section === "library" ? <main className="st-space"><div className="st-space-heading"><div><span className="st-eyebrow">YOUR CREATIVE LIBRARY</span><h1>{trash ? "素材回收站" : "素材库"}</h1><p>{trash ? "保留 30 天。恢复不影响其他作品；彻底删除需再次确认。" : "商品参考、风格灵感与精选作品，随时开始下一次创作。"}</p></div><div className="st-toolbar"><button className="st-secondary" onClick={() => {setTrash(!trash); setLibraryTab("mine"); setFilter("all");}}><Icon name={trash ? "back" : "trash"} size={17}/>{trash ? "返回素材库" : "回收站"}</button><select aria-label="上传素材类型" value={libraryUploadKind} onChange={event => setLibraryUploadKind(event.target.value as typeof libraryUploadKind)}><option value="product">商品图</option><option value="style">风格参考</option><option value="logo">Logo</option></select><label className="st-primary"><Icon name="upload" size={17}/>上传素材<input hidden type="file" multiple accept="image/png,image/jpeg,image/webp" onChange={event => {void upload(Array.from(event.target.files ?? []), libraryUploadKind, true); event.target.value = "";}}/></label></div></div>{!trash && <div className="st-library-switch" aria-label="素材来源"><button className={libraryTab === "mine" ? "active" : ""} aria-pressed={libraryTab === "mine"} onClick={() => {setLibraryTab("mine"); setFilter("all");}}>我的素材</button><button className={libraryTab === "examples" ? "active" : ""} aria-pressed={libraryTab === "examples"} onClick={() => {setLibraryTab("examples"); setFilter("all");}}>平台示例</button></div>}<div className="st-library-controls"><div className="st-tabs">{(libraryTab === "mine" || trash) && [["all", "全部素材"], ["work", "创作作品"], ["product", "商品图片"], ["style", "风格参考"], ["style_preset", "风格预设"], ["logo", "Logo"]].map(([id, label]) => <button className={filter === id ? "active" : ""} key={id} onClick={() => setFilter(id)}>{label}</button>)}</div><label className="st-search"><Icon name="search" size={18}/><input aria-label="搜索素材名称或风格" placeholder="搜索名称或风格" value={search} onChange={event => setSearch(event.target.value)}/></label></div>
        {!trash && libraryTab === "examples" && (filter === "all" || filter === "work" || filter === "style") && demo && <section><div className="st-section-line"><h3>示例作品 <span className="st-count">{demo.items.length}</span></h3><small>已预置 · 无需现场生成</small></div>{demoCards(demo.items.filter(item => (item.title + item.tags.join(" ")).toLocaleLowerCase().includes(search.trim().toLocaleLowerCase())))}</section>}
        {!trash && libraryTab === "examples" && (filter === "all" || filter === "product") && demo && demo.reference.name.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()) && <section><div className="st-section-line"><h3>商品参考</h3><small>原始依据与生成作品分开存放</small></div><div className="st-gallery"><article className="st-art-card"><button className="st-art-image" onClick={() => void act(() => chooseDemoReference(demo.reference.file, "product"))}><img src={demoUrl(demo.reference.file)} alt={demo.reference.name}/><span className="st-image-label">原始参考</span></button><div className="st-art-info"><strong>{demo.reference.name}</strong><span>点击选入当前创作 · 800 × 800</span></div></article></div></section>}
        {(trash || libraryTab === "mine") && <section><div className="st-section-line"><h3>{trash ? "已删除素材" : "我的素材"} <span className="st-count">{filteredLibrary.length}</span></h3></div>{!filteredLibrary.length && <div className="st-empty-small"><Icon name="folder" size={28}/><p>{search.trim() || filter !== "all" ? "没有匹配的素材，请调整搜索或筛选条件。" : trash ? "回收站是空的" : "在生成结果中点击“加入素材库”，保存你的精选作品。"}</p></div>}<div className="st-gallery">{filteredLibrary.map(entry => <article className="st-art-card" key={entry.id}><button className="st-art-image" disabled={trash} onClick={() => {if (entry.payload.versions?.[0]) setSelectedWork(entry); else if (entry.payload.demo) setSelectedDemo(entry.payload.demo); else if (entry.kind === "style_preset") void act(async () => applyStylePreset(entry)); else if (entry.payload.asset) setSelectedAsset(entry.payload.asset);}}>{cardImage(entry) ? <img src={mediaUrl(cardImage(entry))} alt={entry.name}/> : <span className="st-preset-cover"><Icon name="spark" size={28}/>风格预设</span>}{entry.payload.versions && <span className="st-image-label">{entry.payload.versions.length} 张 · 作品快照</span>}</button><div className="st-art-info"><strong>{entry.name}</strong>{entry.expires_at && <span>保留至 {new Date(entry.expires_at).toLocaleDateString()}</span>}<div className="st-card-buttons">{trash ? <><button onClick={() => void act(async () => {await studio.libraryAction(entry.id, "restore"); await refreshLibrary();})}>恢复</button><button className="danger" onClick={() => setConfirm({title: "彻底删除此条目？", message: "此操作无法恢复。其他作品仍在引用的文件不会删除。", run: async () => {await studio.libraryAction(entry.id, "purge"); await refreshLibrary();}})}>彻底删除</button></> : <>{entry.kind === "style_preset" && <button onClick={() => void act(async () => applyStylePreset(entry))}>应用</button>}<button onClick={() => setRename({entry, value: entry.name})}>改名</button>{entry.payload.versions && <button onClick={() => void continueLibraryWork(entry)}>继续编辑</button>}{entry.payload.content && <button onClick={() => void act(async () => {const value = await studio.create(entry.payload.content!.tool); value.content = cleanReuse(entry.payload.content!); const saved = await studio.save(value); await openDraft(saved); setNotice("已复用风格和页面结构，请上传新商品图。");})}>换商品复用</button>}<button aria-label={`删除${entry.name}`} onClick={() => setConfirm({title: "移入回收站？", message: "保留 30 天，到期自动清理。不会连带删除其他创作或已保存副本。", run: async () => {await studio.libraryAction(entry.id, "trash"); await refreshLibrary();}})}><Icon name="trash" size={16}/></button></>}</div></div></article>)}</div></section>}
      </main> : <main className="st-space"><div className="st-space-heading"><div><span className="st-eyebrow">PICK UP WHERE YOU LEFT OFF</span><h1>{historyTrash ? "创作记录回收站" : "创作记录"}</h1><p>{historyTrash ? "已删除记录保留 30 天，可恢复或提前彻底删除。" : "保留输入、任务和历史版本，随时继续。"}</p></div><div className="st-toolbar"><button className="st-secondary" onClick={() => {setHistoryTrash(!historyTrash); setSearch("");}}><Icon name={historyTrash ? "back" : "trash"} size={17}/>{historyTrash ? "返回创作记录" : "回收站"}</button><select aria-label="按创作工具筛选" value={historyTool} onChange={event => setHistoryTool(event.target.value as "all" | Tool)}><option value="all">全部工具</option>{tools.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select><select aria-label="按创作状态筛选" value={historyStatus} onChange={event => setHistoryStatus(event.target.value)}><option value="all">全部状态</option>{Object.entries(historyStatusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><label className="st-search"><Icon name="search" size={18}/><input aria-label="搜索创作记录" placeholder="搜索商品或工具" value={search} onChange={event => setSearch(event.target.value)}/></label></div></div><div className="st-history-list">{historyCards()}</div></main>}
    </div>
    {selectedWork && <Modal busy={busy} title={selectedWork.name} wide onClose={() => setSelectedWork(null)}><div className="st-work-preview"><div className="st-work-preview-grid">{selectedWork.payload.versions!.map((version, index) => <figure key={version.id}><VersionVisual version={version} alt={`作品快照 ${index + 1}`}/><figcaption>{index + 1}. {version.kind === "manual" ? "手动编辑版" : `AI 底图 ${version.review.score ?? "—"} 分`}</figcaption></figure>)}</div><aside><span className="st-eyebrow">INDEPENDENT SNAPSHOT</span><h2>独立作品快照</h2><p>此处只读展示收藏时的页序、成图、图层和质检证据。继续编辑会创建新的创作副本，不覆盖这份收藏。</p><div className="st-info-line"><span>收藏时间</span><strong>{new Date(selectedWork.created_at).toLocaleString("zh-CN")}</strong></div><div className="st-info-line"><span>图片数量</span><strong>{selectedWork.payload.versions!.length} 张</strong></div><div className="st-detail-bottom"><button className="st-primary" onClick={() => {const entry = selectedWork; setSelectedWork(null); void continueLibraryWork(entry);}}><Icon name="edit" size={17}/>创建副本并继续编辑</button><button className="st-secondary" onClick={() => void act(() => downloadZip(selectedWork.payload.versions!.map((version, index) => ({version, filename: `${String(index + 1).padStart(2, "0")}-作品`}))))}><Icon name="download" size={17}/>下载 ZIP</button><button className="st-secondary" onClick={() => void act(() => downloadLongImage(selectedWork.payload.versions!.map((version, index) => ({version, filename: `${String(index + 1).padStart(2, "0")}-作品`}))))}><Icon name="image" size={17}/>拼接长图</button></div></aside></div></Modal>}
    {selectedAsset && <Modal busy={busy} title={selectedAsset.name} onClose={() => setSelectedAsset(null)}><div className="st-asset-preview"><img src={mediaUrl(selectedAsset.source_url)} alt={selectedAsset.name}/><p>{selectedAsset.width} × {selectedAsset.height} px · {selectedAsset.usage === "product" ? "商品参考" : selectedAsset.usage === "style" ? "风格参考" : "Logo"}</p><button className="st-primary" onClick={() => {const value = selectedAsset; setSelectedAsset(null); void act(() => chooseAsset(value, value.usage as "product" | "style" | "logo"));}}>选入当前创作</button></div></Modal>}
    {exportOpen && <Modal busy={busy} title="导出当前选图" onClose={() => setExportOpen(false)}><div className="st-confirm"><p>{selectedIds.length ? "导出勾选的" : "按当前页面顺序导出"} {exportRows.length} 张图片。{!selectedIds.length && (missingExportPages ? `还有 ${missingExportPages} 页没有选图，将不会生成空白占位。` : "所有页面均已有选图。")}</p><div className="st-export-options"><button className="st-secondary" onClick={() => void act(async () => {await downloadZip(exportRows); setExportOpen(false);})}><Icon name="download" size={17}/>整组 ZIP</button><button className="st-secondary" onClick={() => void act(async () => {await downloadLongImage(exportRows); setExportOpen(false);})}><Icon name="image" size={17}/>拼接长图</button></div></div></Modal>}
    {selectedDemo && <Modal busy={busy} title={selectedDemo.title} wide onClose={() => setSelectedDemo(null)}><div className="st-detail-layout"><div className="st-detail-image"><img src={demoUrl(selectedDemo.file)} alt={selectedDemo.title}/></div><aside className="st-detail-info"><span className="st-eyebrow">CONTENT EXAMPLE</span><h2>{selectedDemo.title}</h2><p>{selectedDemo.subtitle}</p><div className="st-info-line"><span>原始尺寸</span><strong>{selectedDemo.width} × {selectedDemo.height}</strong></div><div className="st-info-line"><span>类型</span><strong>平台示例</strong></div><p className="st-note">{selectedDemo.review.note}</p><h4>图像检查记录</h4>{selectedDemo.review.findings.map((finding, index) => <div className="st-finding" key={index}><small>{issueLabels[finding.kind]}</small><p>{finding.message}</p></div>)}<div className="st-detail-bottom"><button className="st-primary" onClick={() => {setSelectedDemo(null); void switchTool(selectedDemo.tool); setNotice("已进入对应工具，可点击“试用示例商品”回填。查看作品不会自动生成。");}}>以此方向开始 <Icon name="arrow" size={17}/></button><button className="st-secondary" onClick={() => void act(() => download(demoUrl(selectedDemo.file), selectedDemo.file))}><Icon name="download" size={17}/>下载原图</button><button className="st-link" onClick={() => void act(async () => {await studio.saveLibrary(selectedDemo.title, "work", {demo: selectedDemo, images: [demoUrl(selectedDemo.file)]}, []); setNotice("已收藏示例作品");})}><Icon name="folder" size={16}/>加入我的素材</button></div></aside></div></Modal>}
    {selectedVersion && <Modal busy={busy} title="图片详情" wide onClose={() => setSelectedVersion(null)}>
      <div className="st-detail-layout">
        <div className="st-version-stage">
          <div className={`st-detail-image ${compare ? "compare" : ""} ${detailFit ? "" : "actual"}`}>
            {compare && compareReferenceId && <figure><img src={mediaUrl(assets[compareReferenceId]?.source_url ?? "")} alt="商品原始参考"/><figcaption>商品原始参考</figcaption></figure>}
            <figure><VersionVisual version={selectedVersion} alt="当前版本"/><figcaption>{selectedVersion.kind === "manual" ? "手动编辑版本" : "当前 AI 成图"}</figcaption></figure>
          </div>
          <div className="st-detail-view-controls">
            {compare && (draft?.content.product_asset_ids.length ?? 0) > 1 && <select aria-label="切换对比参考图" value={compareReferenceId ?? ""} onChange={event => setCompareAssetId(event.target.value)}>{draft?.content.product_asset_ids.map((id, index) => <option key={id} value={id}>{index === 0 ? "主参考" : `商品参考 ${index + 1}`}</option>)}</select>}
            <button className="st-link" onClick={() => setDetailFit(!detailFit)}>{detailFit ? "1:1 查看" : "适应画布"}</button>
          </div>
          <div className={`st-output-proof ${selectedVersion.provenance.matches_requested_pixels === false ? "mismatch" : ""}`}><span>实际 {selectedVersion.width} × {selectedVersion.height} px</span>{selectedVersion.provenance.requested_output && <span>请求 {selectedVersion.provenance.requested_output.width} × {selectedVersion.provenance.requested_output.height} px · High</span>}{selectedVersion.provenance.matches_requested_pixels === false && <em>未拉伸，保留模型实际输出</em>}</div>
          <div className="st-filmstrip">{results.versions.filter(version => version.page_id === selectedVersion.page_id).map(version => <button key={version.id} className={version.id === selectedVersion.id ? "active" : ""} onClick={() => setSelectedVersion(version)}><img src={mediaUrl(version.image_url)} alt={version.kind}/><span>{version.kind === "repair" ? "修复版" : version.kind === "manual" ? "手动版" : "AI 版本"}</span></button>)}</div>
        </div>
        <aside className="st-detail-info st-version-info"><div className="st-detail-scroll"><div className="st-section-line"><h3>{selectedVersion.score_label}</h3><span className="st-score big">{selectedVersion.review.score ?? "—"}</span></div><p className="st-note">{selectedVersion.provenance.note || selectedVersion.review.note}</p>{selectedVersion.kind === "manual" && <p className="st-note">此分数仅对应 AI 底图。手工编辑未重新检查。</p>}{selectedVersion.kind !== "manual" && selectedVersion.review.status !== "completed" && <div className="st-review-state"><p>{selectedReviewTask?.status === "queued" ? `质检已排队（第 ${Math.min(selectedReviewTask.attempt + 1, 3)} 次尝试）` : selectedReviewTask?.status === "running" ? `正在质检（第 ${selectedReviewTask.attempt} 次尝试）` : "质检未完成，不会伪造总分或触发修复。"}</p><button className="st-secondary small" disabled={selectedReviewTask?.status === "queued" || selectedReviewTask?.status === "running"} onClick={() => void queueOrRun(async () => {await studio.recheck(selectedVersion.id); await refresh(selectedVersion.draft_id); setNotice("质检任务已排队，需要执行器领取并完成检查。");})}>手动重检</button></div>}<ReviewFindings key={selectedVersion.id} review={selectedVersion.review}/><button className="st-secondary" onClick={() => setCompare(!compare)}>{compare ? "关闭参考对比" : "对比商品参考"}</button><label className="st-field">AI 修改<textarea maxLength={8000} rows={3} placeholder="描述需要调整的地方。原生图片文字也通过 AI 修改。" value={aiInstruction} onChange={event => setAiInstruction(event.target.value)}/></label><button className="st-secondary" disabled={!aiInstruction.trim() || busy} onClick={() => void generate([selectedVersion.page_id], selectedVersion)}><Icon name="spark" size={17}/>提交 AI 修改</button></div><div className="st-detail-bottom"><button className="st-primary" onClick={() => setEditor(selectedVersion)}><Icon name="edit" size={17}/>手动编辑</button><button className="st-secondary" onClick={() => void act(async () => {await studio.select(selectedVersion.draft_id, selectedVersion.page_id, selectedVersion.id); if (draft) await refresh(draft.id); setNotice("已选用此版本");})}>选用此版本</button><div className="st-two-buttons"><button className="st-secondary" onClick={() => void act(() => downloadVersion(selectedVersion, `作品-${selectedVersion.id.slice(0, 6)}`, "png"))}><Icon name="download" size={16}/>PNG</button><button className="st-secondary" onClick={() => void act(() => downloadVersion(selectedVersion, `作品-${selectedVersion.id.slice(0, 6)}`, "jpg"))}><Icon name="download" size={16}/>JPG</button><button className="st-secondary" onClick={() => void act(() => saveWork([selectedVersion]))}><Icon name="folder" size={16}/>收藏</button></div></div></aside>
      </div>
    </Modal>}
    {picker && <Modal busy={busy} title={picker === "product" ? "选择商品图片" : picker === "style" ? "选择风格参考" : "选择 Logo"} wide onClose={() => setPicker(null)}><div className="st-picker"><p className="st-note">{picker === "product" ? "原始商品图用于外观与身份依据，生成作品不能自动替代。" : picker === "style" ? "参考构图、颜色和氛围，不采用图片中的商品事实或旧文案。" : "Logo 作为明确的品牌素材传给 AI；上传后会同时保存到素材库。"}</p><div className="st-gallery">{picker === "product" && demo && <button className="st-picker-card" onClick={() => void act(() => chooseDemoReference(demo.reference.file, "product"))}><img src={demoUrl(demo.reference.file)} alt="示例商品原始图"/><strong>示例商品 · 原始图</strong></button>}{picker === "style" && demo?.items.map(item => <button className="st-picker-card" key={item.id} onClick={() => void act(() => chooseDemoReference(item.file, "style"))}><img src={demoUrl(item.file)} alt={item.title}/><strong>{item.title}</strong></button>)}{library.filter(entry => !entry.deleted_at && entry.payload.asset?.usage === picker).map(entry => <button key={entry.id} className="st-picker-card" onClick={() => void act(() => chooseAsset(entry.payload.asset!, picker))}><img src={mediaUrl(cardImage(entry))} alt={entry.name}/><strong>{entry.name}</strong></button>)}</div><button className="st-secondary" onClick={() => styleInput.current?.click()}><Icon name="upload" size={17}/>上传新的{picker === "product" ? "商品图" : picker === "style" ? "风格参考" : "Logo"}</button><input hidden ref={styleInput} type="file" multiple={picker !== "logo"} accept="image/png,image/jpeg,image/webp" onChange={event => {void upload(Array.from(event.target.files ?? []), picker); setPicker(null); event.target.value = "";}}/></div></Modal>}
    {serviceOpen && <ServiceConfiguration service={service} onClose={() => setServiceOpen(false)}/>}
    {confirm && <Modal busy={busy} title={confirm.title} onClose={() => setConfirm(null)}><div className="st-confirm"><p>{confirm.message}</p><div><button className="st-secondary" onClick={() => setConfirm(null)}>取消</button><button className="st-primary" onClick={() => {const action = confirm.run; setConfirm(null); void act(action);}}>{confirm.confirmLabel ?? "确认"}</button></div></div></Modal>}
    {rename && <Modal busy={busy} title="重命名素材" onClose={() => setRename(null)}><form className="st-confirm" onSubmit={event => {event.preventDefault(); if (rename.value.trim()) void act(async () => {await studio.libraryAction(rename.entry.id, "rename", rename.value.trim()); setRename(null); await refreshLibrary();});}}><input aria-label="素材名称" autoFocus maxLength={200} value={rename.value} onChange={event => setRename({...rename, value: event.target.value})}/><button type="submit" className="st-primary" disabled={busy || !rename.value.trim()}>保存名称</button></form></Modal>}
    {busy && <div className="st-toast" role="status"><span className="st-spinner"/>正在处理，请稍候…</div>}
    {!busy && notice && <div className="st-toast" role="status"><Icon name="check" size={18}/>{notice}</div>}
  </div>;
}
