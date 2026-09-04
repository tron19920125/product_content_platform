import type {Asset, Catalog, Content, DemoPack, Draft, Layer, LibraryEntry, PlanVersion, Results, Tool, Version} from "./types";

const origin = (import.meta.env.VITE_STUDIO_API_ORIGIN as string | undefined) ?? "";
export const mediaUrl = (value: string) => value.startsWith("/api/") ? `${origin}${value}` : value;
export const demoUrl = (file: string) => `/studio-demo/${encodeURIComponent(file)}`;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${origin}/api/studio${path}`, {...init, headers: {"Content-Type": "application/json", ...init?.headers}});
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = body?.detail;
    throw new Error(typeof detail === "string" ? detail : Array.isArray(detail) ? detail.map((row: {msg: string}) => row.msg).join("；") : `请求失败（${response.status}）`);
  }
  return response.json() as Promise<T>;
}
const json = (method: string, body: unknown) => ({method, body: JSON.stringify(body)});
export const studio = {
  catalog: () => request<Catalog>("/catalog"),
  demos: () => fetch("/studio-demo/manifest.json").then(r => {if (!r.ok) throw new Error("演示素材未安装"); return r.json() as Promise<DemoPack>;}),
  drafts: (tool?: Tool, trash = false) => request<Draft[]>(`/drafts?trash=${trash}${tool ? `&tool=${tool}` : ""}`),
  history: (trash = false) => request<Draft[]>(`/history?trash=${trash}`),
  draft: (id: string) => request<Draft>(`/drafts/${id}`),
  create: (tool: Tool, demo = false) => request<Draft>(demo ? "/demo/drafts" : "/drafts", json("POST", {tool})),
  save: (draft: Draft) => request<Draft>(`/drafts/${draft.id}`, json("PUT", {expected_revision: draft.revision, content: draft.content})),
  draftAction: (id: string, action: "trash" | "restore" | "purge") => request<Draft | {id: string; deleted: boolean}>(`/drafts/${id}/lifecycle`, json("POST", {action})),
  plan: (draft: Draft) => request<Draft>(`/drafts/${draft.id}/plan`, json("POST", {expected_revision: draft.revision})),
  plans: (id: string) => request<PlanVersion[]>(`/drafts/${id}/plans`),
  restorePlan: (draft: Draft, planId: string) => request<Draft>(`/drafts/${draft.id}/plans/${planId}/restore`, json("POST", {expected_revision: draft.revision})),
  asset: (id: string) => request<Asset>(`/assets/${id}`),
  upload: async (file: File, usage: string) => {
    const response = await fetch(`${origin}/api/studio/assets?filename=${encodeURIComponent(file.name)}&usage=${usage}`, {method: "POST", headers: {"Content-Type": "application/octet-stream"}, body: file});
    if (!response.ok) {const error = await response.json(); throw new Error(typeof error.detail === "string" ? error.detail : "图片上传失败");}
    return response.json() as Promise<Asset>;
  },
  generate: (draft: Draft, options: {mode: string; submit_key: string; page_ids?: string[]; source_version_id?: string; instruction?: string}) => request(`/drafts/${draft.id}/generate`, json("POST", {expected_revision: draft.revision, ...options})),
  results: (id: string) => request<Results>(`/drafts/${id}/results`),
  select: (draftId: string, pageId: string, versionId: string) => request<Results>(`/drafts/${draftId}/selection`, json("POST", {page_id: pageId, version_id: versionId})),
  stop: (id: string) => request(`/operations/${id}/stop`, json("POST", {})),
  retry: (id: string) => request(`/jobs/${id}/retry`, json("POST", {})),
  recheck: (id: string) => request(`/versions/${id}/recheck`, json("POST", {})),
  edit: (id: string) => request<{layers: Layer[]; revision: number}>(`/versions/${id}/edit`),
  saveEdit: (id: string, layers: Layer[], revision: number) => request<{layers: Layer[]; revision: number}>(`/versions/${id}/edit`, json("PUT", {layers, expected_revision: revision})),
  apply: (id: string, revision: number, assetId: string) => request<Version>(`/versions/${id}/apply`, json("POST", {expected_revision: revision, rendered_asset_id: assetId})),
  discardEdit: (id: string) => request(`/versions/${id}/edit`, {method: "DELETE"}),
  library: (trash = false) => request<LibraryEntry[]>(`/library?trash=${trash}`),
  saveLibrary: (name: string, kind: string, payload: LibraryEntry["payload"], asset_ids: string[]) => request<LibraryEntry & {already_saved?: boolean}>("/library", json("POST", {name, kind, payload, asset_ids})),
  libraryAction: (id: string, action: string, name = "") => request<LibraryEntry>(`/library/${id}`, json("POST", {action, name})),
  continueWork: (id: string) => request<{draft: Draft; results: Results}>(`/library/${id}/continue`, json("POST", {})),
};
export function freshPage(purpose: string) {return {id: crypto.randomUUID(), purpose, title: "", body: "", visual_goal: "", output: null, skipped: false};}
export function cleanReuse(content: Content): Content {return {...structuredClone(content), product_asset_ids: [], product_name: "", sku: "", category: "", requirements: "", facts: [], pages: content.pages.map(page => ({...page, id: crypto.randomUUID(), title: "", body: "", visual_goal: ""}))};}
