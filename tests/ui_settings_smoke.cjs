const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const e2e=require('./ui_e2e_helper.cjs');
(async()=>{
 const out=path.resolve(process.argv[3]||'工作数据/settings-check');fs.mkdirSync(out,{recursive:true});
 const browser=await e2e.chromium.launch({executablePath:e2e.requireBrowser(),headless:true});
 const page=await browser.newPage({viewport:{width:1366,height:820}}),errors=[],writes=[];
 page.on('pageerror',e=>errors.push(e.message));await require('./ui_composer_fixture.cjs').mockComposer(page);
 const settings={singleMode:'browser',singlePath:'',batchPath:'',dragPath:'',defaultBatchPath:'Z:\\Example\\exports',effectiveBatchPath:'Z:\\Example\\exports',libraryPath:'Z:\\Example\\Library'};
 let exports=null,activeWrites=0,maxActive=0,delayNext=false;
 await page.route('**/api/settings',async route=>{
  if(route.request().method()==='POST'){
   const values=route.request().postDataJSON();writes.push(values);activeWrites++;maxActive=Math.max(maxActive,activeWrites);
   if(delayNext){delayNext=false;await new Promise(r=>setTimeout(r,1000));}
   Object.assign(settings,values);activeWrites--;
  }
  await route.fulfill({json:{...settings}});
 });
 await page.route('**/api/export-file',async route=>{exports=route.request().postDataJSON();await route.fulfill({status:201,json:{path:'Z:\\Example\\single\\角色.png'}});});
 try{
  await page.goto(process.argv[2]);await page.locator('#boot-overlay').waitFor({state:'hidden'});await page.waitForFunction(()=>document.querySelector('#preview').naturalWidth>0);
  await page.locator('#settings-button').click();await page.locator('[data-settings-open="panel-single"]').click();
  await page.locator('input[name="single-save-mode"][value="folder"]').check();
  await page.waitForFunction(()=>document.querySelector('#settings-status').textContent.includes('已保存'));
  delayNext=true;await page.locator('#single-path').fill('Z:\\Example\\first');
  await page.waitForResponse(r=>r.url().endsWith('/api/settings')&&r.request().method()==='POST');
  // Begin another delayed write, then edit and navigate while it is in flight.
  delayNext=true;const before=writes.length;await page.locator('#single-path').fill('Z:\\Example\\old');
  while(writes.length===before)await page.waitForTimeout(25);
  await page.locator('#single-path').fill('Z:\\Example\\latest');
  await page.locator('#nav-workbench').click();await page.locator('#settings-button').click();await page.locator('[data-settings-open="panel-single"]').click();
  assert.equal(await page.locator('#single-path').inputValue(),'Z:\\Example\\latest');
  await page.waitForFunction(()=>document.querySelector('#settings-status').textContent.includes('已保存'));
  assert.equal(settings.singlePath,'Z:\\Example\\latest');assert.equal(maxActive,1);
  assert.equal(await page.locator('#single-path').inputValue(),'Z:\\Example\\latest');
  await page.locator('#settings-back').click();await page.locator('[data-settings-open="panel-batch"]').click();await page.locator('#batch-path').fill('Z:\\Example\\batch');
  await page.waitForFunction(()=>document.querySelector('#settings-status').textContent.includes('已保存'));assert.equal(settings.batchPath,'Z:\\Example\\batch');
  await page.locator('#nav-workbench').click();await page.locator('#download').click();await page.waitForFunction(()=>document.querySelector('#export-status').textContent.includes('已保存'));assert(exports.game&&exports.special===false);
  await page.locator('#settings-button').click();await page.locator('[data-settings-open="panel-single"]').click();await page.screenshot({path:path.join(out,'settings-desktop.png')});
  await page.setViewportSize({width:360,height:740});assert(!(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1)));await page.screenshot({path:path.join(out,'settings-mobile.png'),fullPage:true});
  assert.deepEqual(errors,[]);console.log(JSON.stringify({passed:true,checks:['grouped settings','serialized saves','newer edits survive delayed response and navigation','persisted paths','single export','narrow viewport'],writes:writes.length,maxActive,errors}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
