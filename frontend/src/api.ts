export type ProductProfile = {
  sku: string;
  name: string;
  category: string;
  model: string;
  selling_points: string[];
  parameters: Record<string, string>;
  reference_assets: string[];
  brand_requirements: string;
  output_requirements: string;
};

export type Project = {
  id: string;
  name: string;
  status: string;
  profile: ProductProfile;
  created_at: string;
  updated_at: string;
};

export type BatchItem = {
  id: string;
  project_id: string;
  sku: string;
  status: string;
  error: string;
};

export type Batch = {
  id: string;
  name: string;
  status: string;
  common_config: Record<string, unknown>;
  items: BatchItem[];
  progress: Record<string, number>;
  created_at: string;
  updated_at: string;
};

export type Asset = {
  id: string;
  project_id: string;
  usage: "product" | "detail" | "brand" | "scene";
  file_name: string;
  mime_type: string;
  size_bytes: number;
  source: string;
  authorization_status: "unconfirmed" | "authorized" | "restricted";
  content_url: string;
  created_at: string;
};

export type PageItem = {
  id: string;
  order: number;
  page_type: "hero" | "selling_point" | "function" | "scene" | "parameters";
  title: string;
  body: string;
  visual_goal: string;
  template_id: string;
  heading_level?: 1 | 2 | 3 | 4 | 5;
  status: "draft" | "ready";
};

export type PagePlan = {
  id: string;
  project_id: string;
  version: number;
  confirmed: boolean;
  items: PageItem[];
  created_at: string;
  updated_at: string;
};

export type TemplateDefinition = {
  id: string;
  name: string;
  page_types: string[];
  layout: string;
  safe_area: number;
  width: number;
  height: number;
  size: string;
  text_box: [number, number, number, number];
  product_box: [number, number, number, number];
  composition_instruction: string;
  scene_prompt_hint: string;
  is_builtin: boolean;
  base_template_id?: string;
};

export type ImageCapabilities = {
  model: string;
  qualities: Array<"low" | "medium" | "high">;
  size_presets: Array<{ value: string; label: string; note: string; experimental?: boolean }>;
  custom_size: {
    multiple_of: number;
    max_edge: number;
    max_aspect_ratio: number;
    min_pixels: number;
    max_pixels: number;
    max_square: string;
  };
};

export type SystemPreflight = {
  status: "ready" | "local" | "error";
  generation_mode: "local" | "azure";
  qa_mode: "local" | "azure";
  auth_mode: string;
  checked_at: string;
  components: Array<{
    name: "image_generation" | "vision_ocr" | "llm_review";
    status: "ready" | "skipped" | "error";
    message: string;
    endpoint_host: string;
  }>;
};

export type Recipe = {
  id: string;
  name: string;
  status: string;
  version: number;
  page_types: string[];
  candidate_count: number;
  qa_policy: string;
  prompt_version_id: string;
  model: string;
  model_params: Record<string, unknown>;
  template_ids: string[];
};

export type PromptVersion = {
  id: string;
  prompt_asset_id: string;
  name: string;
  version: number;
  body: string;
  variables: string[];
  status: string;
  change_note: string;
  created_at: string;
};

export type GenerationJob = {
  id: string;
  project_id: string;
  page_id: string;
  recipe_id: string;
  status: "queued" | "running" | "completed" | "failed";
  attempt: number;
  max_attempts: number;
  error: string;
  trace: Record<string, unknown>;
};

export type QAResult = {
  id: string;
  status: "pass" | "review" | "fail";
  score: number;
  issues: Array<{ code: string; severity: string; message: string; repair: string }>;
  evidence: Record<string, unknown>;
  suggested_fix: string;
  repair_applied: boolean;
};

export type Candidate = {
  id: string;
  candidate_index: number;
  score: number;
  rank: number;
  status: string;
  prompt: string;
  metadata?: Record<string, unknown>;
  base_url: string;
  text_layer_url: string;
  composed_url: string;
  qa: QAResult;
};

export type ReviewDecision = {
  id: string;
  candidate_id: string;
  decision: "approved" | "rejected";
  override_reason: string;
};

export type ProductionPage = {
  page: PageItem;
  job: GenerationJob | null;
  candidates: Candidate[];
  decision: ReviewDecision | null;
};

export type ProductionSnapshot = {
  project: Project;
  plan: PagePlan;
  ready_for_export: boolean;
  pages: ProductionPage[];
};

const API_ORIGIN = (import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000/api").replace(/\/api\/?$/, "");
const API_BASE = `${API_ORIGIN}/api`;

export const resolveApiUrl = (path: string) => path.startsWith("http") ? path : `${API_ORIGIN}${path}`;

async function responseError(response: Response): Promise<Error> {
  const payload = await response.json().catch(() => null);
  return new Error(payload?.detail ?? `请求失败 (${response.status})`);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) throw await responseError(response);
  return response.json() as Promise<T>;
}

export const api = {
  getPreflight: () => request<SystemPreflight>("/preflight"),
  listProjects: () => request<Project[]>("/projects"),
  getProject: (id: string) => request<Project>(`/projects/${id}`),
  createProject: (payload: unknown) =>
    request<Project>("/projects", { method: "POST", body: JSON.stringify(payload) }),
  updateProject: (id: string, payload: { project_name: string; profile: ProductProfile }) =>
    request<Project>(`/projects/${id}`, { method: "PUT", body: JSON.stringify(payload) }),
  cloneProject: (id: string) => request<Project>(`/projects/${id}/clone`, { method: "POST" }),
  listBatches: () => request<Batch[]>("/batches"),
  createBatch: (payload: unknown) =>
    request<Batch>("/batches", { method: "POST", body: JSON.stringify(payload) }),
  importBatch: async (name: string, file: File, defaultCategory: string) => {
    const query = new URLSearchParams({ name, file_name: file.name, default_category: defaultCategory });
    const response = await fetch(`${API_BASE}/batches-import?${query}`, {
      method: "POST",
      headers: { "Content-Type": file.type || "application/octet-stream" },
      body: file,
    });
    if (!response.ok) throw await responseError(response);
    return response.json() as Promise<Batch>;
  },
  batchImportTemplateUrl: `${API_BASE}/batches-import-template`,
  listAssets: (projectId: string) => request<Asset[]>(`/projects/${projectId}/assets`),
  uploadAsset: async (projectId: string, file: File, usage: Asset["usage"], authorizationStatus: Asset["authorization_status"]) => {
    const query = new URLSearchParams({ file_name: file.name, usage, source: "user_upload", authorization_status: authorizationStatus });
    const response = await fetch(`${API_BASE}/projects/${projectId}/assets?${query}`, {
      method: "POST",
      headers: { "Content-Type": file.type || "application/octet-stream" },
      body: file,
    });
    if (!response.ok) throw await responseError(response);
    return response.json() as Promise<Asset>;
  },
  assetUrl: (assetId: string) => `${API_BASE}/assets/${assetId}/content`,
  getPlan: async (projectId: string) => {
    const response = await fetch(`${API_BASE}/projects/${projectId}/plan`);
    if (response.status === 404) return null;
    if (!response.ok) throw await responseError(response);
    return response.json() as Promise<PagePlan>;
  },
  generatePlan: (projectId: string) =>
    request<PagePlan>(`/projects/${projectId}/plan`, { method: "POST" }),
  savePlan: (projectId: string, plan: Pick<PagePlan, "items" | "confirmed">) =>
    request<PagePlan>(`/projects/${projectId}/plan`, { method: "PUT", body: JSON.stringify(plan) }),
  listTemplates: () => request<TemplateDefinition[]>("/templates"),
  createTemplate: (payload: { name: string; page_types: string[]; base_template_id: string; size: string }) =>
    request<TemplateDefinition>("/templates", { method: "POST", body: JSON.stringify(payload) }),
  getImageCapabilities: () => request<ImageCapabilities>("/image-capabilities"),
  listRecipes: () => request<Recipe[]>("/recipes"),
  listPrompts: () => request<PromptVersion[]>("/prompts"),
  createPrompt: (payload: unknown) => request<PromptVersion>("/prompts", { method: "POST", body: JSON.stringify(payload) }),
  publishPrompt: (id: string) => request<PromptVersion>(`/prompts/${id}/publish`, { method: "POST" }),
  createRecipe: (payload: unknown) => request<Recipe>("/recipes", { method: "POST", body: JSON.stringify(payload) }),
  publishRecipe: (id: string) => request<Recipe>(`/recipes/${id}/publish`, { method: "POST" }),
  getProduction: (projectId: string) => request<ProductionSnapshot>(`/projects/${projectId}/production`),
  startProduction: (projectId: string, force = false, recipeId = "commerce-detail-v1", quality?: string) =>
    request(`/projects/${projectId}/production/start`, { method: "POST", body: JSON.stringify({ recipe_id: recipeId, force, quality }) }),
  recomposePage: (projectId: string, pageId: string) =>
    request<ProductionSnapshot>(`/projects/${projectId}/pages/${pageId}/recompose`, { method: "POST" }),
  regeneratePage: (projectId: string, pageId: string, recipeId: string, quality?: string) =>
    request<GenerationJob>(`/projects/${projectId}/pages/${pageId}/regenerate`, { method: "POST", body: JSON.stringify({ recipe_id: recipeId, force: true, quality }) }),
  reviewCandidate: (candidateId: string, decision: "approved" | "rejected", overrideReason = "") =>
    request<ReviewDecision>(`/candidates/${candidateId}/review`, { method: "POST", body: JSON.stringify({ decision, override_reason: overrideReason, reviewer: "local-user" }) }),
  exportProject: (projectId: string) => request<{ file_name: string; download_url: string }>(`/projects/${projectId}/export`, { method: "POST" }),
  createRecipeCandidate: (projectId: string, name: string) =>
    request<Recipe>(`/projects/${projectId}/recipe-candidate`, { method: "POST", body: JSON.stringify({ name }) }),
  startBatchProduction: (batchId: string, failedOnly = false, recipeId = "commerce-detail-v1", quality?: string) => request(`/batches/${batchId}/production/${failedOnly ? "retry" : "start"}`, { method: "POST", body: JSON.stringify({ recipe_id: recipeId, force: failedOnly, quality }) }),
  pauseBatch: (batchId: string) => request(`/batches/${batchId}/pause`, { method: "POST" }),
  resumeBatch: (batchId: string) => request(`/batches/${batchId}/resume`, { method: "POST" }),
  exportBatch: (batchId: string) => request<{ file_name: string; download_url: string }>(`/batches/${batchId}/export`, { method: "POST" }),
  resolveUrl: resolveApiUrl,
};
