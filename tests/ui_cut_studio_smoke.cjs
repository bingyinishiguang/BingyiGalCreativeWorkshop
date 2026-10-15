const fs=require('fs'),path=require('path'),assert=require('node:assert/strict'),e2e=require('./ui_e2e_helper.cjs');
(async()=>{
 const browser=await e2e.chromium.launch({executablePath:e2e.requireBrowser(),headless:true});
 const out=process.argv[3];fs.mkdirSync(out,{recursive:true});
 try{
  const page=await browser.newPage({viewport:{width:1920,height:1080}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept(d.type()==='prompt'?'横屏构图预设':undefined));
  await page.goto(process.argv[2]);await page.locator('#boot-overlay').waitFor({state:'hidden'});
  await page.locator('#nav-tools').click();await page.locator('#open-roughcut').click();
  await page.locator('#cut-assets [data-add-asset]').first().click();await page.locator('#cut-sprite-tab').click();await page.locator('#cut-assets [data-add-asset]').first().click();
  await page.locator('#cut-scale').fill('175');await page.locator('#cut-scale').press('Tab');
  await page.locator('#cut-position-y').fill('-300');await page.locator('#cut-position-y').press('Tab');
  await page.locator('#cut-preset-tab').click();await page.locator('#save-composition-preset').click();await page.locator('[data-apply-preset]').last().waitFor();
  await page.locator('#studio-project-settings').click();
  assert(await page.locator('#studio-project-dialog #cut-directory').isVisible());
  assert.equal(await page.locator('#roughcut-page > .editor-directory-bar').count(),0);
  await page.locator('#studio-project-close').click();
  const background=page.locator('.editor-lane[data-lane="background"]');
  await background.locator('.editor-segment').first().click();
  await background.locator('[data-track-collapse]').click();
  assert(await background.locator('.editor-segment').first().isHidden());
  await background.locator('[data-track-collapse]').click();
  await background.locator('[data-track-lock]').click();
  assert(await background.locator('.editor-segment').first().isDisabled());
  const beforeLockedDelete=await page.evaluate(()=>JSON.stringify(cutEditor.snapshot().scenes));
  await background.locator('[data-track-lock]').press('Delete');
  assert.equal(await page.evaluate(()=>JSON.stringify(cutEditor.snapshot().scenes)),beforeLockedDelete);
  await background.locator('[data-track-lock]').click();
  const sizes=[];
  for(const [w,h] of [[1920,1080],[1366,768]]){
   await page.setViewportSize({width:w,height:h});await page.waitForFunction(()=>document.querySelector('.editor-timeline-panel').getBoundingClientRect().bottom<=innerHeight-20);
   const boxes=await page.evaluate(()=>{const box=s=>{const r=document.querySelector(s).getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,right:r.right,bottom:r.bottom};};return {assets:box('.editor-assets'),player:box('.editor-player'),inspector:box('.cut-inspector'),timeline:box('.editor-timeline-panel'),save:box('#cut-save'),export:box('#cut-export'),preset:box('#save-composition-preset'),root:box('#roughcut-page')};});
   assert(boxes.assets.right<boxes.player.x+1);assert(boxes.player.right<boxes.inspector.x+1);assert(boxes.timeline.y>=boxes.player.bottom);
   for(const key of ['assets','player','inspector','timeline','save','export','preset']){assert(boxes[key].width>0,key);assert(boxes[key].bottom<=h+1,key);assert(boxes[key].right<=w+1,key);}
   await page.screenshot({path:path.join(out,`studio-${w}.png`)});sizes.push({w,h,boxes});
  }
  await page.locator('#studio-project-settings').click();await page.locator('#cut-canvas').selectOption('1080x1920');await page.locator('#studio-project-close').click();assert.equal(await page.locator('[data-apply-preset]').count(),0);
  await page.locator('#studio-project-settings').click();await page.locator('#cut-canvas').selectOption('1920x1080');await page.locator('#studio-project-close').click();await page.locator('[data-apply-preset]').last().click();
  await page.locator('#studio-local').click();assert(await page.locator('#cut-assets').isVisible());
  //Mock only the native file picker; real import, storage and asset rendering run on the server.
  const fixture=path.resolve(process.argv[4]);await page.route('**/api/backgrounds/pick',r=>r.fulfill({json:{paths:[fixture]}}));
  await page.locator('#cut-bg-tab').click();await page.locator('#studio-import').click();await page.waitForFunction(()=>document.querySelector('#cut-status').textContent.includes('已处理'));
  await page.locator('#cut-sprite-tab').click();await page.locator('#studio-import').click();assert(await page.locator('#import-dialog').isVisible());await page.locator('#close-import').click();
  await page.locator('#cut-audio-tab').click();assert(await page.locator('#editor-audio-assets').isVisible());
  await page.route('**/api/audio/pick',r=>r.fulfill({json:{paths:[path.join(path.dirname(fixture),'dialogue.wav')]}}));await page.locator('#studio-import').click();await page.waitForFunction(()=>document.querySelector('#cut-status').textContent==='音频导入完成');await page.locator('#editor-audio-list .audio-row').first().waitFor({state:'visible'});assert(await page.locator('#editor-audio-list .audio-row').count()>0);
  await page.locator('#studio-text').click();await page.locator('#studio-add-default-text').waitFor({state:'visible'});assert.equal(await page.locator('.cut-inspector #text-single').count(),0);assert(await page.locator('#studio-text-assets #text-srt').isVisible());assert.equal(await page.locator('.text-bulk-dialog[open]').count(),0);
  await page.locator('#studio-fit-timeline').click();
  const separator=page.getByRole('separator',{name:'素材与预览分隔线',exact:true});await separator.focus();await separator.press('ArrowRight');const layout=await page.evaluate(()=>localStorage.getItem('bingyi-cut-layout-v1'));assert.equal(JSON.parse(layout).left,.325);
  await page.locator('#cut-save').click();await page.waitForFunction(()=>document.querySelector('#cut-status').textContent.includes('已保存'));
  const id=await page.evaluate(()=>cutEditor.snapshot().id);await page.reload();await page.locator('#boot-overlay').waitFor({state:'hidden'});await page.locator('#nav-tools').click();await page.locator('#open-roughcut').click();
  assert.equal(await page.evaluate(()=>localStorage.getItem('bingyi-cut-layout-v1')),layout);
  await page.locator('#studio-project-settings').click();await page.locator('#cut-projects').selectOption(id);await page.waitForFunction(()=>document.querySelector('#cut-status').textContent.includes('已打开'));await page.locator('#studio-project-close').click();
  await page.locator('#cut-export').click();await page.waitForFunction(()=>document.querySelector('#cut-status').textContent.includes('已生成'));
  await page.locator('#cut-back').click();assert(!(await page.locator('body').getAttribute('class')).includes('studio-active'));
  assert.deepEqual(errors,[]);const report={sizes,imported:true,presetRatios:true,reopened:true,exported:true,pageErrors:errors};fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
 }catch(error){const p=browser.contexts()[0]?.pages()[0];if(p){await p.screenshot({path:path.join(out,'failure.png')});console.log(await p.evaluate(()=>({status:document.querySelector('#cut-status')?.textContent})));}throw error;}finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
