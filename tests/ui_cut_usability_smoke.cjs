const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),e2e=require('./ui_e2e_helper.cjs');
(async()=>{
 const browser=await e2e.chromium.launch({executablePath:e2e.requireBrowser(),headless:true}),out=process.argv[3];fs.mkdirSync(out,{recursive:true});
 const page=await browser.newPage({viewport:{width:1366,height:900}}),errors=[];page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
 try{
  await page.goto(process.argv[2]);await page.locator('#boot-overlay').waitFor({state:'hidden'});await page.locator('#nav-tools').click();await page.locator('#open-roughcut').click();
  assert.equal(await page.locator('#studio-project-settings').textContent(),'项目与导出设置');
  assert(await page.locator('#cut-save').getAttribute('title').then(s=>s.includes('工坊')));assert(await page.locator('#cut-export').getAttribute('title').then(s=>s.includes('剪映')));
  assert.equal(await page.locator('#studio-quick-help').count(),0);
  await page.locator('#studio-project-settings').click();assert(await page.locator('#studio-project-dialog #cut-directory').isVisible());
  const name='打磨验证_'+Date.now();await page.locator('#cut-name').fill(name);await page.locator('#cut-name').press('Tab');await page.locator('#studio-project-close').click();
  await page.waitForFunction(name=>document.querySelector('#studio-project-state').textContent===name+' · 未保存修改',name);
  await page.locator('#cut-assets [data-add-asset]').first().click();await page.locator('#cut-save').click();await page.waitForFunction(()=>document.querySelector('#cut-status').textContent.includes('已保存'));
  await page.waitForFunction(()=>document.querySelector('#studio-project-state').textContent.endsWith(' · 已保存'));
  const id=await page.evaluate(()=>cutEditor.snapshot().id);assert(id);
  await page.locator('#studio-project-settings').click();await page.locator('#cut-name').fill(name+'_修改');await page.locator('#cut-name').press('Tab');await page.locator('#studio-project-close').click();await page.waitForFunction(()=>document.querySelector('#studio-project-state').dataset.dirty==='true');
  await page.locator('#studio-project-settings').click();await page.locator('#cut-projects').selectOption(id);await page.waitForFunction(()=>document.querySelector('#cut-status').textContent.includes('已打开'));await page.locator('#studio-project-close').click();await page.waitForFunction(name=>document.querySelector('#studio-project-state').textContent===name+' · 已保存',name);
  // Preserve the real save/reopen test above; exercise presentation of an arbitrary long output path.
  const longPath='F:\\剪映草稿\\'+('可继续编辑的粗剪目录_'.repeat(18));await page.evaluate(text=>{document.querySelector('#cut-status').textContent='已生成 30 秒草稿：'+text+'。请在剪映打开检查。';document.querySelector('#cut-open-output').hidden=false;},longPath);
  const boxes=[];
  for(const [width,height] of [[1366,900],[1920,1080]]){
   await page.setViewportSize({width,height});await page.waitForTimeout(180);
   const layout=await page.evaluate(()=>{const result={};for(const id of ['studio-project-state','studio-project-settings','cut-save','cut-export','cut-status','cut-open-output']){const n=document.getElementById(id),r=n.getBoundingClientRect();result[id]={left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height,scrollWidth:n.scrollWidth,clientWidth:n.clientWidth};}result.bodyWidth=document.documentElement.scrollWidth;return result;});
   for(const id of ['studio-project-settings','cut-save','cut-export','cut-open-output']){assert(layout[id].width>0,id);assert(layout[id].right<=width+1,id);assert(layout[id].bottom<=height+1,id);}
   assert(layout['studio-project-state'].height>0);assert(layout['cut-status'].height>20,'long path should wrap');assert(layout['cut-status'].scrollWidth<=layout['cut-status'].clientWidth+2);assert(layout.bodyWidth<=width+1,'no horizontal page overflow');
   await page.screenshot({path:path.join(out,'usability-'+width+'.png')});boxes.push({width,height,layout});
  }
  assert.deepEqual(errors,[]);fs.writeFileSync(path.join(out,'usability-report.json'),JSON.stringify({boxes,errors},null,2));console.log('PASS: project entry, help removed, dirty/save/reopen state, long output wrapping and 1366/1920 layout');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
