const assert=require('node:assert/strict'),fs=require('fs'),path=require('path'),e2e=require('./ui_e2e_helper.cjs');
(async()=>{
 const browser=await e2e.chromium.launch({executablePath:e2e.requireBrowser(),headless:true}),out=process.argv[3];fs.mkdirSync(out,{recursive:true});
 try{
  const p=await browser.newPage({viewport:{width:1366,height:768}}),errors=[];p.on('pageerror',e=>errors.push(e.message));p.on('dialog',d=>d.accept());
  await p.goto(process.argv[2]);await p.locator('#boot-overlay').waitFor({state:'hidden'});await p.locator('#nav-tools').click();await p.locator('#open-roughcut').click();
  await p.locator('#cut-assets [data-add-asset]').first().click();await p.locator('#cut-sprite-tab').click();const cards=p.locator('#cut-assets .production-tile');await cards.first().locator('.expression-pick input').check();await cards.nth(1).locator('.expression-pick input').check();await p.locator('#cut-create-group').click();await p.locator('#group-save').click();await p.locator('#expression-dialog').waitFor({state:'hidden'});
  await cards.first().locator('[data-add-asset]').click();await p.locator('#actor-expression-group').selectOption({index:1});await p.locator('#cut-scale').fill('170');await p.locator('#cut-scale').press('Tab');
  await p.route('**/api/audio/pick',r=>r.fulfill({json:{paths:[path.resolve(process.argv[4])]}}));await p.locator('#cut-audio-tab').click();await p.locator('#studio-import').click();await p.waitForFunction(()=>document.querySelector('#cut-status').textContent==='音频导入完成');
  const audioId=await p.evaluate(()=>cutV2.audioItems()[0].id);await p.evaluate(()=>cutV2.addClip({...cutV2.audioItems()[0],kind:'bgm'}));
  await p.locator('#studio-script').click();await p.locator('#script-count').waitFor();await p.locator('#script-paste-box summary').click();await p.locator('#script-paste').fill('旁白：放学后。\n女主：Hello, welcome back.\n女主内心：He remembered me.\n男主：Thanks.');await p.locator('#script-add-lines').click();
  const row=i=>p.locator('#script-rows tr').nth(i),field=(i,name)=>row(i).locator(`[data-field="${name}"]`);
  assert.deepEqual(await p.locator('[data-field="kind"]').evaluateAll(ns=>ns.map(n=>n.value)),['narrator','heroine','inner','hero']);assert.deepEqual(await p.locator('[data-field="voice"]').evaluateAll(ns=>ns.map(n=>n.checked)),[false,true,true,false]);
  await p.locator('#script-reviewed').check();await p.locator('#script-build').click();await p.waitForFunction(()=>document.querySelector('#script-status').textContent.includes('绑定音频'));assert.equal(await p.evaluate(()=>cutEditor.scenes.length),1);
  await field(1,'audio').selectOption(audioId);await field(2,'audio').selectOption(audioId);
  await field(0,'hold').fill('1');await field(0,'hold').press('Tab');await field(3,'hold').fill('1.5');await field(3,'hold').press('Tab');await field(1,'pause').fill('.5');await field(1,'pause').press('Tab');
  await field(1,'expression').selectOption({index:2});
  await p.screenshot({path:path.join(out,'review-1366.png')});const rect=await p.locator('#script-build').boundingBox();assert(rect.y+rect.height<768);
  await p.locator('#script-save').click();await p.waitForFunction(()=>document.querySelector('#script-status').textContent.includes('已保存'));
  await p.locator('#script-reviewed').check();await p.locator('#script-build').click();await p.waitForFunction(()=>document.querySelector('#script-status').textContent.includes('已铺入'));
  const built=await p.evaluate(()=>structuredClone(cutEditor.snapshot()));assert.equal(built.scenes.length,4);assert.equal(built.textClips.length,4);assert.equal(built.audioClips.filter(c=>c.kind==='dialogue').length,2);assert.equal(built.audioClips.filter(c=>c.kind==='bgm').length,1);
  for(const c of built.audioClips.filter(c=>c.kind==='dialogue')){assert.equal(c.duration,2.037);assert.equal(c.sourceStart,0);assert.equal(c.subtitles,false);}
  assert.equal(built.scenes[1].actors[0].id,built.scenes[2].actors[0].id);assert.equal(built.scenes[1].actors[0].transform.scaleX,170);
  assert(Math.abs(built.scenes.reduce((t,c)=>t+c.duration,0)-7.73333333333333)<.0001);
  await p.locator('#script-close').click();await p.locator('#editor-undo').click();assert.equal(await p.evaluate(()=>cutEditor.scenes.length),1);assert.equal(await p.evaluate(()=>cutEditor.snapshot().textClips.length),0);assert.equal(await p.evaluate(()=>cutEditor.snapshot().scriptPlan.rows.length),4);
  await p.locator('#editor-redo').click();assert.equal(await p.evaluate(()=>cutEditor.scenes.length),4);
  await p.locator('#cut-save').click();await p.waitForFunction(()=>document.querySelector('#cut-status').textContent.includes('已保存'));const id=await p.evaluate(()=>cutEditor.snapshot().id);
  await p.reload();await p.locator('#boot-overlay').waitFor({state:'hidden'});await p.locator('#nav-tools').click();await p.locator('#open-roughcut').click();await p.locator('#studio-project-settings').click();await p.locator('#cut-projects').selectOption(id);await p.locator('#studio-project-close').click();
  assert.deepEqual(await p.evaluate(()=>cutEditor.snapshot().scriptPlan),built.scriptPlan);await p.locator('#cut-export').click();await p.waitForFunction(()=>document.querySelector('#cut-status').textContent.includes('已生成'));
  await p.screenshot({path:path.join(out,'timeline-1366.png')});await p.setViewportSize({width:1920,height:1080});await p.locator('#studio-script').click();await p.screenshot({path:path.join(out,'review-1920.png')});
  assert.deepEqual(errors,[]);const report={sentences:4,voiceDuration:2.037,total:7.733333,missingAudioBlocked:true,expressionInherited:true,undoRedo:true,reopened:true,exported:true,pageErrors:errors};fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
 }catch(error){const p=browser.contexts()[0]?.pages()[0];if(p){await p.screenshot({path:path.join(out,'failure.png')});console.log(await p.evaluate(()=>({status:document.querySelector('#script-status')?.textContent,cut:document.querySelector('#cut-status')?.textContent})));}throw error;}finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
