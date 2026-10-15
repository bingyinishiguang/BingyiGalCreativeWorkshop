const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium,requireBrowser}=require('./ui_e2e_helper.cjs');
(async()=>{
 const out=path.resolve(process.argv[3]);fs.mkdirSync(out,{recursive:true});
 const browser=await chromium.launch({executablePath:requireBrowser(),headless:true}),page=await browser.newPage({viewport:{width:1366,height:900}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 try{
  await page.route('**/api/data-dir',r=>r.request().method()==='POST'?r.fulfill({status:500,json:{ok:false,error:'测试目录操作失败'}}):r.continue());
  await page.route('**/api/settings/choose-pack-dir',r=>r.fulfill({status:500,json:{error:'测试文件选择框故障'}}));
  await page.goto(process.argv[2]);await page.locator('#boot-overlay').waitFor({state:'hidden'});await page.locator('#settings-button').click();await page.locator('[data-settings-open="panel-data"]').click();
  await page.locator('#open-data-dir').click();await page.waitForFunction(()=>document.querySelector('#data-dir-note').textContent.includes('打开失败'));
  await page.locator('#reset-data-dir').click();await page.waitForFunction(()=>document.querySelector('#data-dir-note').textContent.includes('恢复失败'));
  await page.locator('#settings-back').click();await page.locator('[data-settings-open="panel-packs"]').click();await page.locator('#pack-import-choose').click();
  await page.waitForFunction(()=>document.querySelector('#pack-import-status').textContent.includes('测试文件选择框故障'));
  await page.screenshot({path:path.join(out,'picker-failure.png')});
  await page.unroute('**/api/settings/choose-pack-dir');const picks=['A.zip','B.zip'];await page.route('**/api/settings/choose-pack-dir',r=>r.fulfill({json:{path:picks.shift()}}));
  await page.route('**/api/packs',async r=>{if(r.request().method()==='GET')return r.fulfill({json:{packs:[]}});const value=r.request().postDataJSON();if(value.path==='A.zip')await new Promise(resolve=>setTimeout(resolve,500));await r.fulfill({json:{ok:true,packName:value.path,fileCount:1,games:[]}});});
  await page.locator('#pack-import-choose').click();await page.waitForFunction(()=>document.querySelector('#pack-import-path').value==='A.zip');await page.locator('#pack-import-choose').click();await page.waitForTimeout(750);assert((await page.locator('#pack-import-preview').textContent()).includes('B.zip'));await page.locator('#pack-import-cancel').click();await page.unroute('**/api/packs');
  await page.unroute('**/api/settings/choose-pack-dir');await page.route('**/api/settings/choose-pack-dir',r=>r.fulfill({json:{path:'测试素材包.zip'}}));
  await page.route('**/api/packs',r=>r.request().method()==='POST'?r.fulfill({json:{ok:true,packName:'测试素材',fileCount:1,games:[]}}):r.fulfill({json:{packs:[]}}));
  let restarts=0;await page.route('**/api/rescan',r=>{restarts++;return r.fulfill({json:{ok:true}});});
  page.on('dialog',dialog=>dialog.dismiss());
  await page.locator('#settings-back').click();await page.locator('#nav-tools').click();await page.locator('#open-roughcut').click();await page.locator('#cut-assets [data-add-asset]').first().click();
  await page.locator('#cut-back').click();await page.locator('#settings-button').click();await page.locator('[data-settings-open="panel-packs"]').click();
  await page.locator('#pack-import-choose').click();await page.locator('#pack-import-confirm').waitFor({state:'visible'});await page.locator('#pack-import-confirm').click();
  await page.waitForTimeout(3300);assert.equal(restarts,0,'dirty project must prevent automatic restart');assert((await page.locator('#pack-import-status').textContent()).includes('已保留当前任务'));
  assert.deepEqual(errors,[]);const report={passed:true,checks:['directory open failure','directory reset failure','picker failure detail','stale pack preview rejected','dirty project restart protection'],errors};fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
