import type {Catalog, Content, Draft, Tool} from "./types";

export const canonicalJson = (value: unknown) => JSON.stringify(value, (_key, item: unknown) => {
  if (!item || typeof item !== "object" || Array.isArray(item)) return item;
  const record = item as Record<string, unknown>;
  return Object.fromEntries(Object.keys(record).sort().map(key => [key, record[key]]));
});

export function blankDraft(tool: Tool, catalog: Catalog): Draft {
  const defaults = catalog.tools.find(item => item.id === tool)?.defaults;
  if (!defaults) throw new Error("创作工具尚未加载，请稍后再试");
  const content = structuredClone(defaults);
  content.pages = content.pages.map(page => ({...page, id: crypto.randomUUID()}));
  const now = new Date().toISOString();
  return {id: crypto.randomUUID(), tool, revision: 0, content, created_at: now, updated_at: now,
    deleted_at: null, expires_at: null, history_kind: "draft"};
}

export function isUntouched(content: Content, catalog: Catalog): boolean {
  const defaults = catalog.tools.find(item => item.id === content.tool)?.defaults;
  const comparable = (value: Content) => ({...value, pages: value.pages.map(({id: _id, ...page}) => page)});
  return Boolean(defaults && canonicalJson(comparable(content)) === canonicalJson(comparable(defaults)));
}
