// Use a disposable manual-mode Studio server. This suite never calls Azure.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {mkdir, writeFile} from 'node:fs/promises';
const require = createRequire(import.meta.url);
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || require.resolve('playwright'));
const origin = process.env.STUDIO_TEST_URL || 'http://127.0.0.1:8021';
const output = process.env.STUDIO_TEST_OUTPUT || '/tmp/studio-history-results';
await mkdir(output, {recursive:true});
const browser = await chromium.launch({headless:true, ...(process.env.CHROME_PATH ? {executablePath:process.env.CHROME_PATH} : {})});
const results = [];
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
async function api(path, data, method = 'POST') {
  const response = await fetch(`${origin}/api/studio${path}`, data === undefined ? {} : {method, headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  assert.ok(response.ok, `${path}: ${await response.clone().text()}`);
  return response.json();
}
async function until(read, accept, message) {
  for (let i=0;i<60;i++) {const value = await read(); if (accept(value)) return value; await pause(150);}
  throw new Error(message);
}
const nav = (page, name) => page.locator('.st-nav').getByRole('button', {name,exact:true});
const nameInput = page => page.getByPlaceholder('例如：深色滚筒洗衣机');
const record = (page, id) => page.locator(`[data-draft-id="${id}"]`);
async function start(page) {
  await page.goto(origin);
  await page.locator('.st-input h1').waitFor({state:'attached'});
  await page.waitForFunction(()=>document.querySelector('.st-workspace') && !document.querySelector('.st-workspace').hasAttribute('inert'));
  assert.equal(await page.title(), '商品内容生产平台');
  assert.ok((await page.locator('body').innerText()).includes('新建创作'));
}
async function history(page, tab='generation') {
  await nav(page,'创作记录').click();
  await page.getByRole('tab',{name:tab==='draft'?'草稿':'生成记录',exact:true}).click();
}
async function saved(page, productName) {
  const rows = await until(()=>api('/history'), values=>values.some(row=>row.content.product_name===productName), 'Draft did not autosave');
  await page.waitForFunction(()=>document.querySelector('.st-generate-footer')?.textContent.includes('已保存'));
  return (await api('/history')).find(row=>row.content.product_name===productName);
}
async function test(name, run, viewport={width:1440,height:900}) {
  if (process.env.STUDIO_TEST_FILTER && !new RegExp(process.env.STUDIO_TEST_FILTER).test(name)) return;
  const context = await browser.newContext({viewport});
  await context.addInitScript(()=>{
    if (localStorage.getItem('studio.qa.initialized')) return;
    for (const tool of ['ecom_suite','a_plus_detail','marketing_main_image','scene_image','selling_point_image']) localStorage.setItem(`studio.draft.${tool}`,'new:test');
    localStorage.setItem('studio.tool','ecom_suite'); localStorage.setItem('studio.qa.initialized','yes');
  });
  const page=await context.newPage(); page.setDefaultTimeout(7000);
  const errors=[]; page.on('pageerror',error=>errors.push(error.message));
  try {await run(page); assert.deepEqual(errors,[]); results.push({name,status:'PASS'});}
  catch(error) {results.push({name,status:'FAIL',error:error.stack}); await page.screenshot({path:`${output}/${name}.png`}).catch(()=>{});}
  finally {await context.close();}
  console.log(`${results.at(-1).status}: ${name}${results.at(-1).error?'\n'+results.at(-1).error:''}`);
}

await test('browsing-tools-and-default-controls-creates-no-record',async page=>{
  const before=(await api('/drafts')).length;
  const visibleBefore=(await api('/history')).map(row=>row.id).sort();
  await start(page);
  for (const tool of ['A+ 详情图','营销主图','场景图','卖点图','电商套图']) {await nav(page,tool).click(); await page.locator('.st-input h1').filter({hasText:tool}).waitFor();}
  await nameInput(page).focus(); await page.keyboard.press('Tab');
  await page.getByRole('button',{name:'自动匹配',exact:true}).click();
  await page.getByRole('combobox',{name:'图片比例',exact:true}).selectOption('1:1');
  await page.getByRole('button',{name:'新建创作',exact:true}).click();
  await pause(1000);
  assert.equal((await api('/drafts')).length,before);
  await history(page);
  assert.deepEqual((await api('/history')).map(row=>row.id).sort(),visibleBefore);
  await page.getByRole('tab',{name:'草稿',exact:true}).click();
  assert.deepEqual((await api('/history')).map(row=>row.id).sort(),visibleBefore);
  await page.screenshot({path:`${output}/browsing-drafts.png`});
});

await test('first-edit-autosaves-one-draft-and-resumes-after-reload',async page=>{
  const before=(await api('/drafts')).length;
  await start(page); await nameInput(page).fill('草稿恢复测试');
  const draft=await saved(page,'草稿恢复测试');
  await nameInput(page).fill('草稿恢复测试更新'); await saved(page,'草稿恢复测试更新');
  assert.equal((await api('/drafts')).length,before+1);
  await page.reload(); await page.locator('.st-input h1').waitFor({state:'attached'});
  await page.waitForFunction(()=>document.querySelector('.st-workspace') && !document.querySelector('.st-workspace').hasAttribute('inert'));
  assert.equal(await nameInput(page).inputValue(),'草稿恢复测试更新');
  await history(page); assert.equal(await record(page,draft.id).count(),0);
  await page.getByRole('tab',{name:'草稿',exact:true}).click(); await record(page,draft.id).waitFor();
  await record(page,draft.id).locator('.st-history-open').click();
  assert.equal(await nameInput(page).inputValue(),'草稿恢复测试更新');
});

await test('immediate-navigation-flushes-edits-without-cross-tool-overwrite',async page=>{
  await start(page); await nameInput(page).fill('切换前的套图草稿');
  await nav(page,'场景图').click();
  await page.locator('.st-input h1').filter({hasText:'场景图'}).waitFor();
  await nameInput(page).fill('切换后的场景草稿'); await history(page,'draft');
  await until(()=>api('/history'),rows=>rows.some(row=>row.content.product_name==='切换后的场景草稿'),'Navigation lost edited input');
  await page.getByText('切换后的场景草稿',{exact:true}).first().waitFor();
  await nav(page,'电商套图').click();
  await page.waitForFunction(()=>document.querySelector('.st-input h1')?.textContent==='电商套图' && !document.querySelector('.st-workspace')?.hasAttribute('inert'));
  assert.equal(await nameInput(page).inputValue(),'切换前的套图草稿');
});

await test('new-creation-and-repeated-tool-clicks-do-not-save-empty-rows',async page=>{
  await start(page); await nameInput(page).fill('新建前的草稿'); await saved(page,'新建前的草稿');
  const before=(await api('/drafts')).length;
  for (let i=0;i<3;i++) await page.getByRole('button',{name:'新建创作',exact:true}).click();
  await nav(page,'场景图').click(); await nav(page,'电商套图').click();
  await page.waitForFunction(()=>document.querySelector('.st-input h1')?.textContent==='电商套图' && !document.querySelector('.st-workspace')?.hasAttribute('inert'));
  assert.equal(await nameInput(page).inputValue(),'');
  await pause(1000); assert.equal((await api('/drafts')).length,before);
});

await test('lost-first-save-response-retries-same-id-and-keeps-newer-input',async page=>{
  const before=(await api('/drafts')).length;
  let dropped=false;
  await page.route('**/api/studio/drafts/*',async route=>{
    const request=route.request();
    if (!dropped && request.method()==='PUT' && request.postDataJSON().expected_revision===0) {
      dropped=true; await route.fetch(); await route.abort('failed');
    } else await route.continue();
  });
  await start(page); await nameInput(page).fill('首次保存响应丢失');
  await page.getByRole('button',{name:'重试保存',exact:true}).waitFor();
  await nameInput(page).fill('响应丢失后的新输入');
  const draft=await saved(page,'响应丢失后的新输入');
  assert.equal((await api('/drafts')).length,before+1);
  assert.equal((await api(`/drafts/${draft.id}`)).content.product_name,'响应丢失后的新输入');
  await page.reload(); await page.locator('.st-input h1').waitFor({state:'attached'});
  await page.waitForFunction(()=>document.querySelector('.st-workspace') && !document.querySelector('.st-workspace').hasAttribute('inert'));
  assert.equal(await nameInput(page).inputValue(),'响应丢失后的新输入');
});

await test('typing-during-first-save-does-not-revert-input-or-create-duplicates',async page=>{
  const before=(await api('/drafts')).length;
  let delayed=false;
  await page.route('**/api/studio/drafts/*',async route=>{
    const request=route.request();
    if (!delayed && request.method()==='PUT' && request.postDataJSON().expected_revision===0) {
      delayed=true; const response=await route.fetch(); await pause(1700); await route.fulfill({response});
    } else await route.continue();
  });
  await start(page); await nameInput(page).fill('保存中旧内容');
  await until(async()=>delayed,Boolean,'First save did not begin');
  await nameInput(page).fill('保存中的最新内容');
  await saved(page,'保存中的最新内容');
  assert.equal(await nameInput(page).inputValue(),'保存中的最新内容');
  assert.equal((await api('/drafts')).length,before+1);
});

let completedId;
await test('demo-remains-draft-until-submitted-and-regeneration-stays-in-one-record',async page=>{
  const before=(await api('/drafts')).length;
  await start(page); await page.getByRole('button',{name:'没有素材？试用示例商品',exact:true}).click();
  const draft=await saved(page,'深色滚筒洗衣机'); completedId=draft.id;
  assert.equal(draft.history_kind,'draft');
  await history(page,'draft'); await record(page,draft.id).locator('.st-history-open').click();
  await page.getByRole('button',{name:'回放示例',exact:true}).click();
  await page.locator('.st-result-grid').waitFor();
  await until(()=>api(`/drafts/${draft.id}/results`),row=>row.versions.length===3,'Demo did not complete');
  await page.getByRole('button',{name:'重新生成这一页',exact:true}).first().click();
  await until(()=>api(`/drafts/${draft.id}/results`),row=>row.versions.length===4,'Regeneration did not complete');
  await history(page); await record(page,draft.id).waitFor();
  assert.equal((await api('/drafts')).length,before+1);
  await page.getByRole('tab',{name:'草稿',exact:true}).click(); assert.equal(await record(page,draft.id).count(),0);
  await page.getByRole('tab',{name:'生成记录',exact:true}).click();
  await page.screenshot({path:`${output}/generation-records.png`});
});

await test('tool-entry-restores-unsubmitted-draft-instead-of-completed-work',async page=>{
  assert.ok(completedId);
  const expected=(await api('/drafts?tool=ecom_suite&resume=true'))[0];
  await start(page);
  await page.evaluate(id=>localStorage.setItem('studio.draft.ecom_suite',id),completedId);
  await page.reload(); await page.locator('.st-input h1').waitFor({state:'attached'});
  await page.waitForFunction(()=>document.querySelector('.st-workspace') && !document.querySelector('.st-workspace').hasAttribute('inert'));
  await until(()=>nameInput(page).inputValue(),value=>value===expected.content.product_name,'Wrong draft resumed');
  assert.equal(await page.locator('.st-result-grid').count(),0);
  await history(page); await record(page,completedId).locator('.st-history-open').click();
  await page.locator('.st-result-grid').waitFor();
});

await test('legacy-empty-records-hidden-but-unnamed-reference-draft-is-retained',async page=>{
  const empty=await api('/drafts',{tool:'selling_point_image'});
  const source=await api('/demo/drafts',{tool:'selling_point_image'});
  source.content.product_name='';
  await api(`/drafts/${source.id}`,{expected_revision:source.revision,content:source.content},'PUT');
  await start(page); await history(page,'draft');
  await record(page,source.id).getByText('未命名创作',{exact:true}).waitFor();
  assert.equal(await record(page,empty.id).count(),0);
  assert.equal((await api(`/drafts/${empty.id}`)).id,empty.id);
  await page.screenshot({path:`${output}/saved-drafts.png`});
});

await test('submitted-planning-failure-is-a-generation-record-and-can-be-reopened',async page=>{
  await page.route('**/api/health',async route=>{const response=await route.fetch(); await route.fulfill({json:{...await response.json(),planning_available:true}});});
  await start(page); await nav(page,'A+ 详情图').click();
  await nameInput(page).fill('保留失败的模块规划'); await saved(page,'保留失败的模块规划');
  await page.getByRole('button',{name:'智能生成方案',exact:true}).click();
  await page.getByRole('button',{name:'确认',exact:true}).click();
  await page.getByRole('alert').waitFor();
  const rows=await api('/history'); const draft=rows.find(row=>row.content.product_name==='保留失败的模块规划');
  assert.equal(draft.history_kind,'generation'); assert.equal(draft.history_status,'plan_failed');
  await history(page); await record(page,draft.id).getByText('规划失败',{exact:true}).waitFor();
  await record(page,draft.id).locator('.st-history-open').click();
  await page.getByRole('status').filter({hasText:'模块方案未完成'}).waitFor();
  assert.equal(await nameInput(page).inputValue(),'保留失败的模块规划');
});

await test('history-tabs-keyboard-filtering-and-mobile-layout',async page=>{
  await start(page); await history(page);
  const generation=page.getByRole('tab',{name:'生成记录',exact:true});
  await generation.focus(); await page.keyboard.press('ArrowRight');
  const drafts=page.getByRole('tab',{name:'草稿',exact:true});
  assert.equal(await drafts.getAttribute('aria-selected'),'true');
  assert.equal(await page.getByRole('combobox',{name:'按创作状态筛选'}).isDisabled(),true);
  await page.getByRole('textbox',{name:'搜索创作记录'}).fill('没有这个商品');
  await page.getByText('没有匹配的创作记录，请调整搜索或筛选条件。',{exact:true}).waitFor();
  await page.getByRole('textbox',{name:'搜索创作记录'}).fill('');
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
  await page.screenshot({path:`${output}/mobile-drafts.png`});
},{width:390,height:844});

await browser.close();
await writeFile(`${output}/results.json`,JSON.stringify(results,null,2));
console.log(`${results.filter(row=>row.status==='PASS').length}/${results.length} passed`);
process.exitCode=results.some(row=>row.status==='FAIL')?1:0;
