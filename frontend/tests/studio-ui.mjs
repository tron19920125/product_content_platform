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
async function confirmManualQueue(page) {
  await page.getByRole('dialog', {name: '当前只能加入待执行队列', exact: true}).getByRole('button', {name: '仅加入队列', exact: true}).click();
}
async function test(name, run, viewport = {width: 1440, height: 900}, zoom = 1) {
  if (process.env.STUDIO_TEST_FILTER && !new RegExp(process.env.STUDIO_TEST_FILTER).test(name)) return;
  let context;
  if (zoom === 1) context = await browser.newContext({viewport});
  else {
    // Chromium's default storage partition uses the key "x". This changes
    // browser zoom itself; assert innerWidth and DPR so a no-op cannot pass.
    const profile = `${output}/zoom-profile-${Date.now()}`;
    await mkdir(`${profile}/Default`, {recursive:true});
    await writeFile(`${profile}/Default/Preferences`, JSON.stringify({partition:{default_zoom_level:{x:Math.log(zoom)/Math.log(1.2)}}}));
    context = await chromium.launchPersistentContext(profile, {headless:true, viewport, ...(process.env.CHROME_PATH ? {executablePath:process.env.CHROME_PATH} : {})});
  }
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
  await page.getByRole('button', {name: '平台示例', exact: true}).click();
  await page.getByRole('button', {name: /原始参考/}).click();
  await pause(600);
  assert.equal(await page.locator('.st-workspace').count(), 1, 'Choosing a product must return to current creation');
});
await test('cannot-remove-final-page', async page => {
  await seed(); await ready(page);
  await page.getByRole('button', {name: '第 3 页更多操作', exact: true}).click();
  await page.getByRole('menuitem', {name: '移除第 3 页', exact: true}).click();
  await page.getByRole('button', {name: '第 2 页更多操作', exact: true}).click();
  await page.getByRole('menuitem', {name: '移除第 2 页', exact: true}).click();
  await page.getByRole('button', {name: '第 1 页更多操作', exact: true}).click();
  assert.equal(await page.getByRole('menuitem', {name: '移除第 1 页', exact: true}).isDisabled(), true, 'Keep at least one page so autosave remains valid');
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
  await page.locator('.st-history-item').first().getByRole('button', {name: /^更多操作/}).click();
  await page.getByRole('menuitem', {name: /^删除/}).click();
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
  // Exercise a provider failure after a configured planner passes preflight.
  await page.route('**/api/health', async route => {const response = await route.fetch(); await route.fulfill({json: {...await response.json(), planning_available: true}});});
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
  await nav(page, '素材库').click(); await page.locator('.st-tabs').getByRole('button', {name: '风格预设', exact: true}).click();
  await page.getByRole('button', {name: '改名', exact: true}).first().click();
  await page.getByRole('textbox', {name: '素材名称', exact: true}).fill('  ');
  assert.equal(await page.getByRole('button', {name: '保存名称', exact: true}).isDisabled(), true);
  const name = `键盘改名-${crypto.randomUUID()}`;
  await page.getByRole('textbox', {name: '素材名称', exact: true}).fill(name); await page.keyboard.press('Enter');
  await page.getByRole('dialog').waitFor({state: 'hidden'});
  await page.getByPlaceholder('搜索名称或风格').fill('没有这个素材_xyz');
  await page.getByText('没有匹配的素材，请调整搜索或筛选条件。', {exact: true}).waitFor();
});
await test('selected-export-and-page-order', async page => {
  await seed('ecom_suite', true); await ready(page);
  await page.getByRole('button', {name: '第 3 页更多操作', exact: true}).click();
  await page.getByRole('menuitem', {name: '上移第 3 页', exact: true}).click();
  const labels = await page.locator('.st-result-grid .st-card-title>strong').allTextContents();
  assert.deepEqual(labels, ['营销主图', '卖点图', '场景图']);
  await page.getByRole('checkbox', {name: '勾选图片用于批量操作'}).nth(1).check();
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
  await confirmManualQueue(page);
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
  await confirmManualQueue(page);
  await page.getByRole('alert').waitFor();
  await page.getByRole('button', {name: '开始生成', exact: true}).click();
  await confirmManualQueue(page);
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
await test('unconfigured-service-explains-next-steps', async page => {
  await seed(); await ready(page);
  await page.getByRole('status', {name: '服务连接状态'}).getByText('自动生图尚未配置', {exact: true}).waitFor();
  await page.getByRole('button', {name: '查看配置', exact: true}).click();
  const dialog = page.getByRole('dialog', {name: '服务配置与连接状态', exact: true});
  await dialog.getByText('未接入自动执行器', {exact: true}).waitFor();
  await dialog.getByText('当前 Studio 未接入', {exact: true}).waitFor();
  assert.match(await dialog.textContent(), /复用原 Azure 配置/);
  await page.screenshot({path: `${output}/service-configuration.png`});
  await dialog.getByRole('button', {name: '返回工作台', exact: true}).click();
  await dialog.waitFor({state: 'hidden'});
});
await test('manual-queue-requires-confirmation-and-is-not-running', async page => {
  const {draft} = await seed(); await ready(page);
  await page.getByRole('button', {name: '开始生成', exact: true}).click();
  const dialog = page.getByRole('dialog', {name: '当前只能加入待执行队列', exact: true});
  await dialog.getByRole('button', {name: '取消', exact: true}).click();
  assert.equal((await api(`/drafts/${draft.id}/results`)).operations.length, 0);
  await page.getByRole('button', {name: '开始生成', exact: true}).click();
  await confirmManualQueue(page);
  await page.locator('.st-progress').getByText('等待执行', {exact: true}).waitFor();
  assert.equal(await page.locator('.st-progress .st-spinner').count(), 0);
  const results = await api(`/drafts/${draft.id}/results`);
  assert.equal(results.operations.length, 1);
  assert.ok(results.operations[0].jobs.every(job => job.status === 'queued'));
  await nav(page, '创作记录').click();
  await page.locator('.st-history-item').first().getByText('等待执行', {exact: true}).waitFor();
  assert.equal((await api('/history')).find(row => row.id === draft.id).history_status, 'queued');
});
await test('service-disconnect-and-recheck-preserve-input', async page => {
  await seed(); await ready(page);
  const original = await page.getByPlaceholder('例如：深色滚筒洗衣机').inputValue();
  await page.getByRole('button', {name: '查看配置', exact: true}).click();
  const dialog = page.getByRole('dialog', {name: '服务配置与连接状态', exact: true});
  await page.route('**/api/health', route => route.abort('failed'));
  await dialog.getByRole('button', {name: '重新检测', exact: true}).click();
  await dialog.getByText('连接失败', {exact: true}).waitFor();
  assert.equal(await dialog.getByText('待检测', {exact: true}).count(), 4);
  await page.unroute('**/api/health');
  await dialog.getByRole('button', {name: '重新检测', exact: true}).click();
  await dialog.getByText('已连接', {exact: true}).waitFor();
  await dialog.getByRole('button', {name: '返回工作台', exact: true}).click();
  assert.equal(await page.getByPlaceholder('例如：深色滚筒洗衣机').inputValue(), original);
});
await test('unconfigured-planning-opens-configuration', async page => {
  await seed(); await seed('a_plus_detail'); await ready(page); await nav(page, 'A+ 详情图').click();
  let plans = 0;
  await page.route('**/api/studio/drafts/*/plan', route => {plans++; return route.abort();});
  await page.getByRole('button', {name: '智能生成方案', exact: true}).click();
  await page.getByRole('dialog', {name: '服务配置与连接状态', exact: true}).getByText('未配置，可手动编辑方案', {exact: true}).waitFor();
  assert.equal(plans, 0);
});
await test('initial-disconnection-recovers-without-page-reload', async page => {
  await seed();
  await page.route('**/api/health', route => route.abort('failed'));
  await page.goto(origin);
  await page.getByRole('status', {name: '服务连接状态'}).getByText('创作服务已断开', {exact: true}).waitFor();
  await page.getByRole('button', {name: '查看配置', exact: true}).click();
  const dialog = page.getByRole('dialog', {name: '服务配置与连接状态', exact: true});
  await page.unroute('**/api/health');
  await dialog.getByRole('button', {name: '重新检测', exact: true}).click();
  await dialog.getByText('已连接', {exact: true}).waitFor();
  await dialog.getByRole('button', {name: '返回工作台', exact: true}).click();
  await page.locator('.st-ref-grid img').first().waitFor({state: 'attached'});
});
await test('demo-replay-works-without-auto-generation', async page => {
  await seed(); await ready(page);
  await page.getByRole('button', {name: /试用示例商品/}).click();
  await page.getByRole('button', {name: '回放示例', exact: true}).click();
  await page.locator('.st-result-grid .st-art-card').first().waitFor();
  assert.equal(await page.getByRole('dialog', {name: '当前只能加入待执行队列', exact: true}).count(), 0);
});
await test('azure-ready-submits-without-manual-queue-warning', async page => {
  const {draft} = await seed();
  await page.route('**/api/health', route => route.fulfill({json: {
    status: 'ok', workspace: 'studio', generation_available: true, generation_submission_available: true,
    planning_available: true, demo_available: true, azure_configured: true, generation_provider: 'azure', executor_state: 'ready',
  }}));
  await ready(page);
  await page.getByRole('button', {name: '服务配置', exact: true}).click();
  const dialog = page.getByRole('dialog', {name: '服务配置与连接状态', exact: true});
  await dialog.getByText('Azure 自动生图已启动', {exact: true}).waitFor();
  await dialog.getByRole('button', {name: '返回工作台', exact: true}).click();
  await page.getByRole('button', {name: '开始生成', exact: true}).click();
  await page.locator('.st-progress').waitFor();
  assert.equal(await page.getByRole('dialog', {name: '当前只能加入待执行队列', exact: true}).count(), 0);
  assert.equal((await api(`/drafts/${draft.id}/results`)).operations.length, 1);
});
await test('azure-auth-error-blocks-submission-and-explains-recovery', async page => {
  const {draft} = await seed();
  let recovered = false;
  await page.route('**/api/health', route => route.fulfill({json: {
    status: 'ok', workspace: 'studio', generation_available: recovered, generation_submission_available: true,
    planning_available: true, demo_available: true, azure_configured: true, generation_provider: 'azure',
    executor_state: recovered ? 'ready' : 'error', generation_error: recovered ? '' : 'Azure 认证已失效，请恢复登录或更新密钥，再重新检测并重试失败任务。',
  }}));
  await ready(page);
  await page.getByRole('status', {name: '服务连接状态'}).getByText('生图服务需要处理', {exact: true}).waitFor();
  await page.getByRole('button', {name: '开始生成', exact: true}).click();
  const dialog = page.getByRole('dialog', {name: '服务配置与连接状态', exact: true});
  await dialog.getByText('已暂停，请处理下方问题', {exact: true}).waitFor();
  assert.match(await dialog.textContent(), /恢复登录或更新密钥/);
  assert.equal((await api(`/drafts/${draft.id}/results`)).operations.length, 0);
  await page.screenshot({path: `${output}/azure-auth-reminder.png`});
  recovered = true;
  await dialog.getByRole('button', {name: '重新检测', exact: true}).click();
  await dialog.getByText('Azure 自动生图已启动', {exact: true}).waitFor();
});
for (const width of [1280, 1440, 1000]) await test(`layout-${width}`, async page => {
  await seed('ecom_suite', true); await ready(page);
  if (width < 1280) await page.getByRole('button', {name: '创作设置', exact: true}).click();
  const button = page.getByRole('button', {name: '开始生成', exact: true});
  const r = await button.boundingBox(); assert.ok(r && r.y + r.height <= 720 && r.x >= 0);
  if (width < 1280) await page.getByRole('button', {name: '关闭创作设置', exact: true}).click();
  await page.screenshot({path: `${output}/studio-${width}.png`});
  await page.getByRole('button', {name: '查看图片详情', exact: true}).first().click();
  await page.getByRole('button', {name: '对比商品参考', exact: true}).click();
  await page.getByRole('img', {name: '商品原始参考', exact: true}).waitFor();
  await page.getByRole('button', {name: '1:1 查看', exact: true}).click();
  await page.getByRole('button', {name: '适应画布', exact: true}).click();
  const close = await page.getByRole('button', {name: '关闭', exact: true}).boundingBox();
  assert.ok(close && close.x + close.width <= width && close.y >= 0);
  await page.screenshot({path: `${output}/detail-${width}.png`});
}, {width, height: 720});

await test('purpose-menu-keyboard-size-and-undo', async page => {
  const {draft} = await seed('ecom_suite', true); await ready(page);
  const trigger = page.getByRole('button', {name: '第 2 页更多操作', exact: true});
  await trigger.focus(); await page.keyboard.press('Enter');
  assert.equal(await page.getByRole('menuitem', {name: '上移第 2 页', exact: true}).evaluate(el => el === document.activeElement), true);
  await page.keyboard.press('ArrowDown'); await page.keyboard.press('Enter');
  assert.deepEqual(await page.locator('.st-purpose-heading>strong').allTextContents(), ['营销主图', '卖点图', '场景图']);
  await page.getByLabel('第 1 页输出尺寸', {exact: true}).selectOption('3:4|1k');
  await page.locator('.st-purpose-card').first().getByText('单独设置', {exact: true}).waitFor();
  await page.getByRole('button', {name: '第 3 页更多操作', exact: true}).click();
  await page.getByRole('menuitem', {name: '移除第 3 页', exact: true}).click();
  assert.equal(await page.locator('.st-result-grid .st-art-card').count(), 2);
  await page.getByRole('button', {name: '撤销移除', exact: true}).click();
  assert.equal(await page.locator('.st-result-grid .st-art-card').count(), 3);
  await pause(1200); await page.reload(); await ready(page);
  assert.equal(await page.getByLabel('第 1 页输出尺寸', {exact: true}).inputValue(), '3:4|1k');
  assert.equal((await api(`/drafts/${draft.id}`)).content.pages[2].id, draft.content.pages[1].id);
  await page.getByRole('button', {name: '第 1 页更多操作', exact: true}).click();
  await page.keyboard.press('Escape');
  assert.equal(await page.getByRole('menu').count(), 0);
  assert.equal(await page.getByRole('button', {name: '第 1 页更多操作', exact: true}).evaluate(el => el === document.activeElement), true);
});
await test('a-plus-module-editing-and-result-stage', async page => {
  const {draft} = await seed('a_plus_detail', true); await ready(page);
  await nav(page, 'A+ 详情图').click();
  await page.locator('.st-result-grid').waitFor();
  assert.equal(await page.locator('.st-plan-grid').count(), 0, 'Existing A+ results should be the default stage');
  await page.getByRole('button', {name: '编辑方案与模块', exact: true}).click();
  await page.getByRole('textbox', {name: '模块 1 标题', exact: true}).fill('全新模块标题');
  await page.getByRole('button', {name: '下一个模块', exact: true}).click();
  await page.getByRole('textbox', {name: '模块 2 文案', exact: true}).fill('较长的正文在单个编辑面板内清晰展示。');
  await page.getByRole('button', {name: '上一个模块', exact: true}).click();
  assert.equal(await page.getByRole('textbox', {name: '模块 1 标题', exact: true}).inputValue(), '全新模块标题');
  await pause(1300);
  const saved = await api(`/drafts/${draft.id}`);
  assert.equal(saved.content.pages[0].title, '全新模块标题');
  assert.match(saved.content.pages[1].body, /单个编辑面板/);
  await page.screenshot({path: `${output}/a-plus-editor.png`});
  await page.getByRole('button', {name: /^查看结果/}).click();
  assert.equal(await page.locator('.st-result-grid .st-art-card').count(), 3);
  assert.equal(saved.content.pages[0].id, draft.content.pages[0].id);
});
await test('library-defaults-to-my-assets-and-history-resumes', async page => {
  const {draft} = await seed('ecom_suite', true); await ready(page);
  await nav(page, '素材库').click();
  assert.equal(await page.getByRole('button', {name: '我的素材', exact: true}).getAttribute('aria-pressed'), 'true');
  assert.equal(await page.getByRole('heading', {name: /^示例作品/}).count(), 0);
  await page.getByRole('button', {name: '平台示例', exact: true}).click();
  await page.getByRole('heading', {name: /^示例作品/}).waitFor();
  await page.getByRole('button', {name: '我的素材', exact: true}).click();
  await page.screenshot({path: `${output}/library-mine.png`});
  await nav(page, '创作记录').click();
  await page.screenshot({path: `${output}/history-rows.png`});
  await page.locator('.st-history-open').first().click();
  await page.locator('.st-result-grid').waitFor();
  assert.equal(await page.evaluate(() => localStorage.getItem('studio.draft.ecom_suite')), draft.id);
});
await test('detail-footer-focus-and-ai-edit-submission', async page => {
  const {draft} = await seed('ecom_suite', true); await ready(page);
  await page.getByRole('button', {name: '查看图片详情', exact: true}).first().click();
  const dialog = page.getByRole('dialog', {name: '图片详情', exact: true});
  assert.equal(await dialog.locator('.st-detail-scroll').evaluate(el => el.scrollTop), 0, 'Opening details must start at the QA summary');
  const rect = await dialog.getByRole('button', {name: '选用此版本', exact: true}).boundingBox();
  assert.ok(rect && rect.y + rect.height < 900, 'Main actions stay visible without scrolling');
  await dialog.getByRole('button', {name: '选用此版本', exact: true}).click();
  await dialog.getByRole('textbox', {name: 'AI 修改', exact: true}).fill('保持商品外观，背景增加柔和日光。');
  await page.screenshot({path: `${output}/detail-readable.png`});
  const submitted = page.waitForRequest(request => request.url().endsWith(`/drafts/${draft.id}/generate`));
  await dialog.getByRole('button', {name: '提交 AI 修改', exact: true}).click();
  await confirmManualQueue(page);
  const body = (await submitted).postDataJSON();
  assert.ok(body.source_version_id);
  assert.equal(body.instruction, '保持商品外观，背景增加柔和日光。');
  assert.equal(body.page_ids.length, 1);
});
await test('partial-failure-and-unknown-show-safe-actions', async page => {
  const {draft, results: saved} = await seed('ecom_suite', true);
  const fixture = structuredClone(saved);
  fixture.operations[0].jobs[0].status = 'failed'; fixture.operations[0].jobs[0].error = '模型服务暂时不可用，请重试此项。';
  fixture.operations[0].jobs[1].status = 'unknown'; fixture.operations[0].jobs[1].error = '结果待确认，请勿重复提交。';
  await page.route(`**/api/studio/drafts/${draft.id}/results`, route => route.fulfill({json: fixture}));
  let retries = 0;
  await page.route('**/api/studio/jobs/*/retry', route => {retries++; return route.fulfill({json: {}});});
  await ready(page);
  assert.equal(await page.locator('.st-result-grid .st-art-card').count(), 3, 'Successful images remain visible');
  await page.getByText('结果待确认', {exact: true}).waitFor();
  assert.equal(await page.getByRole('button', {name: '重试此项', exact: true}).count(), 1, 'Unknown jobs must not offer retry');
  await page.getByRole('button', {name: '补生成失败项', exact: true}).click();
  await confirmManualQueue(page); await pause(200);
  assert.equal(retries, 1);
});

async function auditReadable(page, name) {
  const report = await page.evaluate(() => {
    const text = [...document.querySelectorAll('body *')].filter(el => !el.closest('.st-canvas-stage,option,script,style') && el.checkVisibility() && [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim()));
    return text.map(el => ({selector: el.className || el.tagName, text: el.textContent.trim().slice(0, 55), font: parseFloat(getComputedStyle(el).fontSize)})).filter(row => row.font < 13);
  });
  assert.deepEqual(report, [], `${name}: business text must be at least 13px`);
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false, `${name}: no horizontal page overflow`);
}
for (const [width, height] of [[1440,900],[1280,800],[1024,768],[796,885],[390,844]]) await test(`readable-responsive-${width}`, async page => {
  await seed('ecom_suite', true); await ready(page);
  await auditReadable(page, 'results');
  const dimensions = await page.locator('.st-purpose-size select').first().evaluate(el => ({font:parseFloat(getComputedStyle(el).fontSize), height:el.getBoundingClientRect().height}));
  assert.ok(dimensions.font >= 14 && dimensions.height >= 40);
  await page.screenshot({path: `${output}/readable-results-${width}.png`});
  if (width < 1280) await page.getByRole('button', {name: '创作设置', exact: true}).click();
  const button = await page.getByRole('button', {name: '开始生成', exact: true}).boundingBox();
  assert.ok(button && button.y >= 0 && button.y + button.height <= height);
  await page.getByPlaceholder('例如：深色滚筒洗衣机').fill(`窄屏保存-${width}`);
  await pause(1000);
  await auditReadable(page, 'settings');
  if (width < 1280) await page.getByRole('button', {name: '关闭创作设置', exact: true}).click();
  await page.getByRole('button', {name: '查看图片详情', exact: true}).first().click();
  await auditReadable(page, 'details');
  await page.getByRole('button', {name: '选用此版本', exact: true}).click();
  await page.screenshot({path: `${output}/readable-detail-${width}.png`});
  await page.getByRole('button', {name: '关闭', exact: true}).click();
  await openEditor(page);
  if (width < 1024) await page.getByRole('button', {name: '内容与图层', exact: true}).click();
  await page.getByRole('button', {name: '添加文字', exact: true}).click();
  await page.getByRole('textbox', {name: '画布内编辑文字', exact: true}).fill('清晰可读的编辑文案');
  await page.keyboard.press('Escape');
  if (width < 1024) await page.getByRole('button', {name: '对象属性', exact: true}).click();
  await page.getByRole('spinbutton', {name: 'X 位置', exact: true}).fill('100');
  await page.getByRole('spinbutton', {name: '宽度', exact: true}).fill('700');
  await auditReadable(page, 'editor');
  await page.screenshot({path: `${output}/readable-editor-${width}.png`});
  if (width < 1024) await page.getByRole('button', {name: '关闭属性面板', exact: true}).click();
  await page.getByRole('button', {name: '返回工作台', exact: true}).click();
  await nav(page, '素材库').click(); await auditReadable(page, 'library');
  await nav(page, '创作记录').click(); await auditReadable(page, 'history');
}, {width, height});

await test('real-browser-200-percent-zoom-and-drawer-keyboard', async page => {
  await seed('ecom_suite', true); await ready(page);
  assert.deepEqual(await page.evaluate(() => ({width:innerWidth,height:innerHeight,dpr:devicePixelRatio})), {width:720,height:450,dpr:2});
  await auditReadable(page, '200% results');
  const trigger = page.getByRole('button', {name:'创作设置',exact:true});
  await trigger.focus(); await page.keyboard.press('Enter');
  const close = page.getByRole('button', {name:'关闭创作设置',exact:true});
  assert.equal(await close.evaluate(el => el === document.activeElement), true, 'Drawer should focus its close action');
  const generate = page.getByRole('button', {name:'开始生成',exact:true});
  const rect = await generate.boundingBox();
  assert.ok(rect && rect.y + rect.height <= 450 && rect.y >= 0);
  await generate.focus(); await page.keyboard.press('Tab');
  assert.equal(await close.evaluate(el => el === document.activeElement), true, 'Tab wraps within settings');
  await page.keyboard.press('Escape');
  assert.equal(await trigger.evaluate(el => el === document.activeElement), true, 'Escape returns focus');
  await page.getByRole('button', {name:'查看图片详情',exact:true}).first().click();
  await page.getByRole('button', {name:'选用此版本',exact:true}).click();
  await auditReadable(page, '200% details');
  await page.screenshot({path:`${output}/real-zoom-200-detail.png`});
  await page.getByRole('button', {name:'关闭',exact:true}).click();
  await openEditor(page);
  await page.getByRole('button', {name:'内容与图层',exact:true}).click();
  await page.getByRole('button', {name:'添加文字',exact:true}).click();
  assert.equal(await page.getByRole('textbox', {name:'画布内编辑文字',exact:true}).evaluate(el => el === document.activeElement), true, 'New text keeps focus after the layer drawer closes');
  await page.getByRole('textbox', {name:'画布内编辑文字',exact:true}).fill('200% 缩放正常编辑');
  await page.keyboard.press('Escape');
  await page.getByRole('button', {name:'对象属性',exact:true}).click();
  await page.getByRole('spinbutton', {name:'字号',exact:true}).fill('42');
  await page.keyboard.press('Escape');
  assert.equal(await page.getByRole('button', {name:'对象属性',exact:true}).evaluate(el => el === document.activeElement), true, 'Escape closes the property drawer and restores focus');
  await page.getByRole('button', {name:'对象属性',exact:true}).click();
  await auditReadable(page, '200% editor');
  await page.screenshot({path:`${output}/real-zoom-200-editor.png`});
}, {width:1440,height:900}, 2);

await test('text-contrast-and-target-sizes', async page => {
  await seed('ecom_suite', true); await ready(page);
  await page.locator('.st-result-grid .st-art-card').first().waitFor();
  async function measure(selectors) {
    return page.evaluate(selectors => {
      const rgb = value => (value.match(/[\d.]+/g) || []).map(Number);
      const lum = color => color.slice(0,3).map(v => {v/=255; return v <= .04045 ? v/12.92 : ((v+.055)/1.055)**2.4;}).reduce((a,v,i) => a+v*[.2126,.7152,.0722][i],0);
      return selectors.map(selector => {
        const el = document.querySelector(selector); if (!el) return {selector,missing:true};
        const ancestors = []; for(let node=el;node;node=node.parentElement) ancestors.unshift(node);
        let background = [255,255,255];
        for(const node of ancestors) {const color=rgb(getComputedStyle(node).backgroundColor); const alpha=color[3]??1; background=background.map((v,i) => color[i]*alpha+v*(1-alpha));}
        const style=getComputedStyle(el), color=rgb(style.color), l1=lum(color), l2=lum(background), rect=el.getBoundingClientRect();
        return {selector,contrast:(Math.max(l1,l2)+.05)/(Math.min(l1,l2)+.05),font:parseFloat(style.fontSize),height:rect.height,width:rect.width};
      });
    }, selectors);
  }
  const report = await measure(['.st-results-heading p','.st-purpose-heading>strong','.st-purpose-size select','.st-card-title strong','.st-score','.st-card-buttons button','.st-result-actions small','.st-field input','.st-primary','.st-nav nav button.active']);
  await page.getByRole('button', {name:'查看图片详情',exact:true}).first().click();
  report.push(...await measure(['.st-output-proof','.st-finding p','.st-finding>span','.st-note','.st-filmstrip span']));
  await writeFile(`${output}/contrast-and-targets.json`, JSON.stringify(report,null,2));
  assert.ok(report.every(row => !row.missing && row.contrast >= 4.5), JSON.stringify(report.filter(row => row.missing || row.contrast<4.5)));
  assert.ok(report.filter(row => /select|button|input|primary/.test(row.selector)).every(row => row.height>=36));
});

await test('editor-numeric-keyboard-input-is-not-prematurely-clamped', async page => {
  const {results: initial} = await seed('ecom_suite', true); await ready(page); await openEditor(page);
  await page.getByRole('button', {name:'添加文字',exact:true}).click();
  await page.keyboard.press('Escape');
  const width = page.getByRole('spinbutton', {name:'宽度',exact:true});
  await width.focus(); await page.keyboard.press('ControlOrMeta+A'); await page.keyboard.type('700'); await page.keyboard.press('Tab');
  assert.equal(await width.inputValue(), '700');
  const position = page.getByRole('spinbutton', {name:'X 位置',exact:true});
  await position.focus(); await page.keyboard.press('ControlOrMeta+A'); await page.keyboard.type('-25'); await page.keyboard.press('Tab');
  assert.equal(await position.inputValue(), '-25');
  const font = page.getByRole('spinbutton', {name:'字号',exact:true});
  await font.focus(); await page.keyboard.press('ControlOrMeta+A'); await page.keyboard.type('42'); await page.keyboard.press('Tab');
  assert.equal(await font.inputValue(), '42');
  await page.getByRole('button', {name:'返回工作台',exact:true}).click();
  const first = initial.versions.find(version => version.page_id === initial.operations[0].snapshot.content.pages[0].id);
  const saved = await api(`/versions/${first.id}/edit`);
  assert.equal(saved.layers[0].width,700); assert.equal(saved.layers[0].x,-25); assert.equal(saved.layers[0].fontSize,42);
});

await browser.close();
await writeFile(`${output}/results.json`, JSON.stringify(results, null, 2));
console.log(`${results.filter(row => row.status === 'PASS').length}/${results.length} passed`);
process.exitCode = results.some(row => row.status === 'FAIL') ? 1 : 0;
