// Run against a disposable Studio data root; this suite creates and trashes fixtures.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {mkdir, writeFile, readFile} from 'node:fs/promises';
const require = createRequire(import.meta.url);
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || require.resolve('playwright'));
const origin = process.env.STUDIO_TEST_URL || 'http://127.0.0.1:8021';
const output = process.env.STUDIO_TEST_OUTPUT || '/private/tmp/product-studio-ui-results';
await mkdir(output, {recursive: true});
const browser = await chromium.launch({headless: true, ...(process.env.CHROME_PATH ? {executablePath: process.env.CHROME_PATH} : {})});
const results = [];
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
async function api(path, data, method = 'POST') {
  const response = await fetch(`${origin}/api/studio${path}`, data === undefined ? {} : {method, headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)});
  assert.ok(response.ok, `${path}: ${await response.clone().text()}`);
  return response.json();
}
async function seed(tool = 'ecom_suite', generated = false) {
  const draft = await api('/demo/drafts', {tool});
  if (generated) {
    await api(`/drafts/${draft.id}/generate`, {expected_revision: draft.revision, submit_key: crypto.randomUUID(), mode: 'demo'});
    for (let i = 0; i < 80; i++) {
      const value = await api(`/drafts/${draft.id}/results`);
      if (value.versions.length === draft.content.pages.length) return {draft, results: value};
      await pause(100);
    }
    throw Error('Demo did not finish');
  }
  return {draft};
}
async function ready(page) {
  await page.goto(origin);
  await page.locator('.st-ref-grid img').first().waitFor({state: 'attached'});
}
async function test(name, run, viewport = {width: 1440, height: 900}) {
  if (process.env.STUDIO_TEST_FILTER && !new RegExp(process.env.STUDIO_TEST_FILTER).test(name)) return;
  const context = await browser.newContext({viewport});
  const page = await context.newPage();
  page.setDefaultTimeout(4000);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    await run(page, context);
    assert.deepEqual(errors, [], 'Unhandled browser errors');
    results.push({name, status: 'PASS'});
  } catch (error) {
    results.push({name, status: 'FAIL', error: error.stack});
    await page.screenshot({path: `${output}/${name}.png`}).catch(() => {});
  } finally {await context.close();}
  console.log(`${results.at(-1).status}: ${name}${results.at(-1).error ? '\n' + results.at(-1).error : ''}`);
}
const nav = (page, name) => page.locator('.st-nav').getByRole('button', {name, exact: true});
async function openEditor(page) {
  await page.locator('.st-result-grid').getByRole('button', {name: '编辑', exact: true}).first().click();
  await page.getByRole('button', {name: '完成编辑', exact: true}).waitFor();
  await page.waitForFunction(() => document.querySelector('.st-editor-header')?.textContent.includes('已保存'));
}

await test('rapid-tool-navigation', async page => {
  await seed(); await ready(page);
  await page.route('**/api/studio/drafts?trash=false&tool=scene_image', async route => {await pause(500); await route.continue();});
  await nav(page, '场景图').click();
  await nav(page, '电商套图').click();
  await pause(900);
  assert.equal(await page.locator('.st-input h1').textContent(), '电商套图', 'Last navigation intent must win');
});
await test('library-pick-returns-to-creation', async page => {
  await seed(); await ready(page);
  await nav(page, '素材库').click();
  await page.getByRole('button', {name: /原始参考/}).click();
  await pause(600);
  assert.equal(await page.locator('.st-workspace').count(), 1, 'Choosing a product must return to current creation');
});
await test('cannot-remove-final-page', async page => {
  await seed(); await ready(page);
  await page.getByRole('button', {name: '移除第 3 页', exact: true}).click();
  await page.getByRole('button', {name: '移除第 2 页', exact: true}).click();
  assert.equal(await page.getByRole('button', {name: '移除第 1 页', exact: true}).isDisabled(), true, 'Keep at least one page so autosave remains valid');
});
await test('modal-focus-containment', async page => {
  await seed(); await ready(page);
  await page.getByRole('button', {name: '素材库选择', exact: true}).click();
  assert.equal(await page.evaluate(() => !!document.activeElement?.closest('[role=dialog]')), true, 'Opening a dialog must move focus inside');
  await page.getByRole('dialog').getByRole('button').last().focus();
  await page.keyboard.press('Tab');
  assert.equal(await page.evaluate(() => !!document.activeElement?.closest('[role=dialog]')), true, 'Tab must not escape');
  await page.keyboard.press('Escape');
  assert.equal(await page.evaluate(() => document.activeElement?.textContent), '素材库选择', 'Restore focus to the trigger');
});
await test('deleted-current-draft-not-reopened', async page => {
  const {draft} = await seed(); await ready(page);
  await nav(page, '创作记录').click();
  await page.locator('.st-history-item').first().getByRole('button', {name: /^删除/}).click();
  await page.getByRole('button', {name: '确认', exact: true}).click();
  await page.waitForResponse(response => response.url().endsWith(`/drafts/${draft.id}/lifecycle`));
  await nav(page, '电商套图').click();
  await page.getByPlaceholder('例如：深色滚筒洗衣机').fill('删除后继续创作');
  await pause(1300);
  assert.equal(await page.getByRole('alert').count(), 0, 'Returning after deletion must not save into a trashed draft');
  assert.equal((await api(`/drafts/${draft.id}`)).content.product_name, draft.content.product_name, 'A trashed record must remain unchanged');
});
await test('editor-discard-clears-pending-save-and-undo', async page => {
  const {results: initial} = await seed('ecom_suite', true); await ready(page); await openEditor(page);
  await page.getByRole('button', {name: '添加文字', exact: true}).click();
  await page.getByRole('textbox', {name: '画布内编辑文字'}).fill('旧草稿');
  await page.getByRole('button', {name: '返回工作台', exact: true}).click();
  await openEditor(page);
  await page.getByRole('button', {name: '添加文字', exact: true}).click();
  await page.getByRole('button', {name: '丢弃草稿', exact: true}).click();
  await pause(1300);
  assert.equal(await page.getByRole('button', {name: '撤销', exact: true}).isDisabled(), true, 'Discarded objects must not survive in undo history');
  assert.equal(await page.locator('.st-layer-list>div').count(), 0);
  const editedVersion = initial.versions.find(value => value.page_id === initial.operations[0].snapshot.content.pages[0].id);
  const editing = await api(`/versions/${editedVersion.id}/edit`);
  assert.equal(editing.revision, 0, 'A pending autosave must not recreate a discarded draft');
});
await test('upload-does-not-cross-drafts', async page => {
  await api('/drafts', {tool: 'scene_image'});
  await seed(); await ready(page);
  let started; const uploading = new Promise(resolve => {started = resolve;});
  await page.route('**/api/studio/assets?*', async route => {started(); await pause(700); await route.continue();});
  const manifest = await api('/demo');
  const buffer = Buffer.from(await (await fetch(`${origin}/studio-demo/${manifest.reference.file}`)).arrayBuffer());
  await page.locator('.st-upload input').setInputFiles({name: 'slow.jpg', mimeType: 'image/jpeg', buffer});
  await uploading;
  await nav(page, '场景图').click();
  await pause(1800);
  const title = await page.locator('.st-input h1').textContent();
  if (title === '场景图') assert.equal(await page.locator('.st-ref-grid img').count(), 0, 'An upload from another tool must never be attached here');
});
await test('compact-settings-have-close-button', async page => {
  await seed(); await page.goto(origin);
  await page.getByRole('button', {name: '创作设置', exact: true}).click();
  const close = page.getByRole('button', {name: '关闭创作设置', exact: true});
  assert.equal(await close.count(), 1, 'Settings drawer needs an accessible close control');
  await close.click();
  assert.equal(await page.locator('.st-input').isVisible(), false);
}, {width: 1000, height: 720});

await test('navigation-to-library-cancels-tool-load', async page => {
  await seed(); await ready(page);
  await page.route('**/api/studio/drafts?trash=false&tool=scene_image', async route => {await pause(500); await route.continue();});
  await nav(page, '场景图').click(); await nav(page, '素材库').click(); await pause(900);
  assert.equal(await page.locator('.st-space h1').textContent(), '素材库');
});
await test('tool-and-demo-replay-survive-reload', async page => {
  await seed(); await ready(page);
  await nav(page, '场景图').click();
  await page.getByRole('button', {name: /试用示例商品/}).click();
  await page.getByRole('button', {name: '回放示例', exact: true}).waitFor();
  await page.reload();
  await page.locator('.st-ref-grid img').waitFor();
  assert.equal(await page.locator('.st-input h1').textContent(), '场景图');
  assert.equal(await page.getByRole('button', {name: '回放示例', exact: true}).count(), 1, 'Reloading a demo must not silently change its generation mode');
});
await test('history-error-is-visible-and-handled', async page => {
  await seed(); await ready(page); await nav(page, '创作记录').click();
  await page.route('**/api/studio/drafts/*', route => route.fulfill({status: 503, json: {detail: '读取记录失败，请重试'}}));
  await page.locator('.st-history-open').first().click();
  await page.getByRole('alert').waitFor();
  assert.match(await page.getByRole('alert').textContent(), /读取记录失败/);
});
await test('autosave-failure-preserves-input-and-retries', async page => {
  const {draft} = await seed(); await ready(page);
  let fail = true;
  await page.route(`**/api/studio/drafts/${draft.id}`, route => route.request().method() === 'PUT' && fail ? route.fulfill({status: 503, json: {detail: '暂时无法保存'}}) : route.continue());
  await page.getByPlaceholder('例如：深色滚筒洗衣机').fill('断网后仍保留的商品');
  await page.getByRole('button', {name: '重试保存', exact: true}).waitFor();
  assert.equal(await page.getByPlaceholder('例如：深色滚筒洗衣机').inputValue(), '断网后仍保留的商品');
  fail = false; await page.getByRole('button', {name: '重试保存', exact: true}).click();
  await page.waitForFunction(() => document.querySelector('.st-generate-footer')?.textContent.includes('已保存'));
  assert.equal((await api(`/drafts/${draft.id}`)).content.product_name, '断网后仍保留的商品');
});
await test('a-plus-planning-failure-preserves-edits', async page => {
  await seed(); await seed('a_plus_detail'); await ready(page); await nav(page, 'A+ 详情图').click();
  await page.getByRole('textbox', {name: '模块 1 标题', exact: true}).fill('我的标题');
  await page.route('**/api/studio/drafts/*/plan', route => route.fulfill({status: 503, json: {detail: '规划服务暂时不可用'}}));
  await page.getByRole('button', {name: '智能生成方案', exact: true}).click();
  await page.getByRole('button', {name: '确认', exact: true}).click();
  await page.getByRole('alert').waitFor();
  assert.equal(await page.getByRole('textbox', {name: '模块 1 标题', exact: true}).inputValue(), '我的标题');
});
await test('picker-excludes-trash-and-shows-errors-above-dialog', async page => {
  const {draft} = await seed();
  const asset = await api(`/assets/${draft.content.product_asset_ids[0]}`);
  const entry = await api('/library', {name: `已删除商品-${crypto.randomUUID()}`, kind: 'product', payload: {asset, images: [asset.source_url]}, asset_ids: [asset.id]});
  await api(`/library/${entry.id}`, {action: 'trash'});
  await ready(page); await nav(page, '素材库').click(); await page.getByRole('button', {name: '回收站', exact: true}).click();
  await nav(page, '电商套图').click(); await page.getByRole('button', {name: '素材库选择', exact: true}).click();
  await pause(200);
  assert.equal(await page.getByRole('dialog').getByText(entry.name).count(), 0);
  await page.route('**/api/studio/assets?*', route => route.fulfill({status: 413, json: {detail: '测试上传失败'}}));
  await page.getByRole('button', {name: /示例商品 · 原始图/}).click();
  await page.getByRole('alert').waitFor();
  assert.equal(await page.getByRole('alert').evaluate(element => {const r = element.getBoundingClientRect(); return element.contains(document.elementFromPoint(r.x + 30, r.y + r.height / 2));}), true, 'Errors must not be hidden behind a modal');
});
await test('empty-library-search-and-rename-keyboard', async page => {
  await seed(); await ready(page); await page.getByRole('button', {name: '保存为风格预设', exact: true}).click();
  await nav(page, '素材库').click(); await page.getByRole('button', {name: '风格预设', exact: true}).click();
  await page.getByRole('button', {name: '改名', exact: true}).first().click();
  await page.getByRole('textbox', {name: '素材名称'}).fill('  ');
  assert.equal(await page.getByRole('button', {name: '保存名称', exact: true}).isDisabled(), true);
  const name = `键盘改名-${crypto.randomUUID()}`;
  await page.getByRole('textbox', {name: '素材名称'}).fill(name); await page.keyboard.press('Enter');
  await page.getByRole('dialog').waitFor({state: 'hidden'});
  await page.getByPlaceholder('搜索名称或风格').fill('没有这个素材_xyz');
  await page.getByText('没有匹配的素材，请调整搜索或筛选条件。', {exact: true}).waitFor();
});
await test('selected-export-and-page-order', async page => {
  await seed('ecom_suite', true); await ready(page);
  await page.getByRole('button', {name: '上移第 3 页', exact: true}).click();
  const labels = await page.locator('.st-result-grid .st-card-title>strong').allTextContents();
  assert.deepEqual(labels, ['营销主图', '卖点图', '场景图']);
  await page.getByRole('checkbox', {name: '选择图片'}).nth(1).check();
  await page.getByRole('button', {name: '导出', exact: true}).click();
  assert.match(await page.getByRole('dialog').textContent(), /导出勾选的\s*1 张/);
  const downloading = page.waitForEvent('download');
  await page.getByRole('button', {name: '整组 ZIP', exact: true}).click();
  const file = await downloading; const bytes = await readFile(await file.path());
  const filenames = []; let offset = 0;
  while (bytes.readUInt32LE(offset) === 0x04034b50) {const size = bytes.readUInt32LE(offset + 18), n = bytes.readUInt16LE(offset + 26), extra = bytes.readUInt16LE(offset + 28); filenames.push(bytes.subarray(offset + 30, offset + 30 + n).toString()); offset += 30 + n + extra + size;}
  assert.deepEqual(filenames, ['01-卖点图.png']);
});
await test('editor-finish-is-atomic-and-downloads-match', async page => {
  const {results: initial} = await seed('ecom_suite', true); await ready(page); await openEditor(page);
  await page.getByRole('button', {name: '添加文字', exact: true}).click();
  await page.getByRole('textbox', {name: '画布内编辑文字'}).fill('最终文字'); await page.keyboard.press('Escape');
  let started; const uploading = new Promise(resolve => {started = resolve;});
  await page.route('**/api/studio/assets?*', async route => {started(); await pause(500); await route.continue();});
  await page.getByRole('button', {name: '完成编辑', exact: true}).click(); await uploading;
  assert.equal(await page.getByRole('button', {name: '返回工作台', exact: true}).isDisabled(), true);
  assert.equal(await page.locator('.st-editor-body').getAttribute('inert'), '', 'Edits must be frozen while completing');
  await page.getByRole('dialog', {name: '图片详情', exact: true}).waitFor();
  const current = (await api(`/drafts/${initial.versions[0].draft_id}/results`)).versions.find(value => value.kind === 'manual');
  assert.equal(current.layers[0].text, '最终文字');
  assert.equal(current.parent_id, initial.versions.find(value => value.page_id === current.page_id).id);
  for (const format of ['PNG', 'JPG']) {
    const downloading = page.waitForEvent('download'); await page.getByRole('button', {name: format, exact: true}).click();
    const file = await downloading, bytes = await readFile(await file.path());
    assert.ok(bytes.length > 1000);
    assert.equal(bytes.subarray(0, 2).toString('hex'), format === 'PNG' ? '8950' : 'ffd8');
  }
});
await test('editor-lock-undo-redo-and-text-shortcuts', async page => {
  await seed('ecom_suite', true); await ready(page); await openEditor(page);
  await page.getByRole('button', {name: '添加文字', exact: true}).click();
  await page.getByRole('textbox', {name: '画布内编辑文字'}).fill('不要删除整层');
  await page.keyboard.press('Backspace'); assert.equal(await page.locator('.st-layer-list>div').count(), 1);
  await page.keyboard.press('Escape');
  await page.getByRole('button', {name: '锁定图层', exact: true}).click();
  assert.equal(await page.getByRole('button', {name: '删除图层', exact: true}).isDisabled(), true);
  assert.equal(await page.getByRole('spinbutton', {name: '字号', exact: true}).isDisabled(), true);
  await page.getByRole('button', {name: '解锁图层', exact: true}).click();
  await page.getByRole('button', {name: '删除图层', exact: true}).click();
  await page.getByRole('button', {name: '撤销', exact: true}).click(); assert.equal(await page.locator('.st-layer-list>div').count(), 1);
  await page.getByRole('button', {name: '重做', exact: true}).click(); assert.equal(await page.locator('.st-layer-list>div').count(), 0);
});
await test('submit-double-click-and-stop', async page => {
  const {draft} = await seed(); await ready(page);
  await page.getByPlaceholder('例如：深色滚筒洗衣机').fill('自定义队列测试');
  await page.getByRole('button', {name: '开始生成', exact: true}).evaluate(element => {element.click(); element.click();});
  await page.getByRole('button', {name: '停止后续生成', exact: true}).waitFor();
  assert.equal((await api(`/drafts/${draft.id}/results`)).operations.length, 1);
  await page.getByRole('button', {name: '停止后续生成', exact: true}).click();
  await page.waitForFunction(() => !document.querySelector('.st-progress'));
  const current = await api(`/drafts/${draft.id}/results`);
  assert.ok(current.operations[0].jobs.every(job => job.status === 'stopped'));
});
await test('lost-submit-response-does-not-duplicate-jobs', async page => {
  const {draft} = await seed(); await ready(page);
  let lost = true;
  await page.route(`**/api/studio/drafts/${draft.id}/generate`, async route => {
    const response = await route.fetch();
    if (lost) {lost = false; await route.abort('failed');} else await route.fulfill({response});
  });
  await page.getByRole('button', {name: '开始生成', exact: true}).click();
  await page.getByRole('alert').waitFor();
  await page.getByRole('button', {name: '开始生成', exact: true}).click();
  await pause(500);
  assert.equal((await api(`/drafts/${draft.id}/results`)).operations.length, 1, 'Retrying an unacknowledged submission must reuse its identity');
});
await test('library-work-continue-reuse-and-long-image', async page => {
  const {draft} = await seed('ecom_suite', true); await ready(page);
  await page.getByRole('button', {name: '加入素材库', exact: true}).click();
  await nav(page, '素材库').click(); await page.getByRole('button', {name: '创作作品', exact: true}).click();
  const work = page.locator('.st-art-card').filter({has: page.getByRole('button', {name: '继续编辑', exact: true})}).first();
  await work.locator('.st-art-image').click();
  const downloading = page.waitForEvent('download');
  await page.getByRole('button', {name: '拼接长图', exact: true}).click();
  const file = await downloading, bytes = await readFile(await file.path());
  assert.equal(bytes.readUInt32BE(16), 2048);
  assert.ok(bytes.readUInt32BE(20) > 2048);
  await page.getByRole('button', {name: '创建副本并继续编辑', exact: true}).click();
  await page.locator('.st-result-grid .st-art-card').first().waitFor();
  const copies = await api('/drafts?tool=ecom_suite');
  assert.notEqual(copies[0].id, draft.id);
  assert.equal(await page.locator('.st-result-grid .st-art-card').count(), 3);
  await nav(page, '素材库').click(); await work.getByRole('button', {name: '换商品复用', exact: true}).click();
  await page.waitForFunction(() => document.querySelector('.st-upload-empty'));
  assert.equal(await page.getByPlaceholder('例如：深色滚筒洗衣机').inputValue(), '');
  assert.equal(await page.getByRole('button', {name: '开始生成', exact: true}).isDisabled(), true);
});
await test('reference-limit-is-checked-before-upload', async page => {
  await seed();
  await page.route('**/api/studio/catalog', async route => {const response = await route.fetch(); const value = await response.json(); value.limits.total_references = 1; await route.fulfill({json: value});});
  await ready(page);
  await page.getByRole('button', {name: '参考图 +', exact: true}).click();
  await page.getByRole('dialog').getByRole('button').nth(1).click();
  await page.getByRole('alert').waitFor();
  assert.match(await page.getByRole('alert').textContent(), /合计最多 1 张/);
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('.st-style-refs img').count(), 0);
});
await test('all-five-tools-keep-independent-drafts', async page => {
  await seed(); await ready(page);
  const names = ['电商套图', 'A+ 详情图', '营销主图', '场景图', '卖点图'];
  for (const name of names) {
    await nav(page, name).click();
    await page.waitForFunction(name => document.querySelector('.st-input h1')?.textContent === name, name);
    await page.getByPlaceholder('例如：深色滚筒洗衣机').fill(`独立草稿-${name}`);
  }
  for (const name of names) {
    await nav(page, name).click();
    await page.waitForFunction(name => document.querySelector('.st-input h1')?.textContent === name, name);
    assert.equal(await page.getByPlaceholder('例如：深色滚筒洗衣机').inputValue(), `独立草稿-${name}`);
  }
});
await test('new-creation-preserves-previous-draft', async page => {
  const {draft} = await seed(); await ready(page);
  await page.getByPlaceholder('例如：深色滚筒洗衣机').fill('需要保留的旧商品');
  await page.getByRole('button', {name: '新建创作', exact: true}).click();
  await page.locator('.st-upload-empty').waitFor();
  assert.equal(await page.getByPlaceholder('例如：深色滚筒洗衣机').inputValue(), '');
  assert.equal((await api(`/drafts/${draft.id}`)).content.product_name, '需要保留的旧商品');
});
await test('library-upload-trash-restore-purge', async page => {
  await seed(); await ready(page); await nav(page, '素材库').click();
  const manifest = await api('/demo');
  const buffer = Buffer.from(await (await fetch(`${origin}/studio-demo/${manifest.reference.file}`)).arrayBuffer());
  const name = `素材生命周期-${crypto.randomUUID()}.jpg`;
  await page.locator('.st-space-heading input[type=file]').setInputFiles({name, mimeType: 'image/jpeg', buffer});
  let card = page.locator('.st-art-card').filter({has: page.locator('.st-art-info>strong', {hasText: name})});
  await card.getByRole('button', {name: `删除${name}`, exact: true}).click();
  await page.getByRole('button', {name: '确认', exact: true}).click();
  await card.waitFor({state: 'hidden'});
  await page.getByRole('button', {name: '回收站', exact: true}).click();
  await card.getByRole('button', {name: '恢复', exact: true}).click();
  await card.waitFor({state: 'hidden'});
  await page.getByRole('button', {name: '返回素材库', exact: true}).click();
  await card.getByRole('button', {name: `删除${name}`, exact: true}).click();
  await page.getByRole('button', {name: '确认', exact: true}).click(); await card.waitFor({state: 'hidden'});
  await page.getByRole('button', {name: '回收站', exact: true}).click();
  await card.getByRole('button', {name: '彻底删除', exact: true}).click();
  await page.getByRole('button', {name: '确认', exact: true}).click(); await card.waitFor({state: 'hidden'});
});
await test('editor-drag-resize-image-and-persist', async page => {
  const {draft, results: initial} = await seed('ecom_suite', true); await ready(page); await openEditor(page);
  const manifest = await api('/demo');
  const buffer = Buffer.from(await (await fetch(`${origin}/studio-demo/${manifest.reference.file}`)).arrayBuffer());
  await page.locator('.st-editor-tools input[type=file]').setInputFiles({name: 'logo.jpg', mimeType: 'image/jpeg', buffer});
  const layer = page.locator('.st-layer-overlay'); await layer.waitFor();
  await page.getByRole('spinbutton', {name: '旋转角度', exact: true}).fill('30');
  const handle = page.getByRole('button', {name: '缩放所选对象', exact: true});
  const r = await handle.boundingBox();
  await page.mouse.move(r.x + r.width / 2, r.y + r.height / 2); await page.mouse.down();
  await page.mouse.move(r.x + r.width / 2 + 45, r.y + r.height / 2 + 30, {steps: 8}); await page.mouse.up();
  await page.getByRole('button', {name: '隐藏图层', exact: true}).click();
  assert.equal(await layer.count(), 0);
  await page.getByRole('button', {name: '显示图层', exact: true}).click();
  await page.screenshot({path: `${output}/editor-1440.png`});
  await page.getByRole('button', {name: '返回工作台', exact: true}).click();
  const source = initial.versions.find(value => value.page_id === draft.content.pages[0].id);
  const edited = await api(`/versions/${source.id}/edit`);
  assert.equal(edited.layers.length, 1); assert.equal(edited.layers[0].rotation, 30);
  assert.ok(Math.abs(edited.layers[0].width / edited.layers[0].height - 1) < .001);
  assert.ok(edited.layers[0].width > source.width * .3, 'Dragging the rotated resize handle should enlarge the image');
});
for (const width of [1280, 1440, 1000]) await test(`layout-${width}`, async page => {
  await seed('ecom_suite', true); await ready(page);
  if (width < 1280) await page.getByRole('button', {name: '创作设置', exact: true}).click();
  const button = page.getByRole('button', {name: '开始生成', exact: true});
  const r = await button.boundingBox(); assert.ok(r && r.y + r.height <= 720 && r.x >= 0);
  if (width < 1280) await page.getByRole('button', {name: '关闭创作设置', exact: true}).click();
  await page.screenshot({path: `${output}/studio-${width}.png`});
  await page.getByRole('button', {name: '生成结果', exact: true}).first().click();
  await page.getByRole('button', {name: '对比商品参考', exact: true}).click();
  await page.getByRole('img', {name: '商品原始参考', exact: true}).waitFor();
  await page.getByRole('button', {name: '1:1 查看', exact: true}).click();
  await page.getByRole('button', {name: '适应画布', exact: true}).click();
  const close = await page.getByRole('button', {name: '关闭', exact: true}).boundingBox();
  assert.ok(close && close.x + close.width <= width && close.y >= 0);
  await page.screenshot({path: `${output}/detail-${width}.png`});
}, {width, height: 720});

await browser.close();
await writeFile(`${output}/results.json`, JSON.stringify(results, null, 2));
console.log(`${results.filter(row => row.status === 'PASS').length}/${results.length} passed`);
process.exitCode = results.some(row => row.status === 'FAIL') ? 1 : 0;
