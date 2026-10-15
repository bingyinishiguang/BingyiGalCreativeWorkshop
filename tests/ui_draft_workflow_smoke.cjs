const assert=require('node:assert/strict'),fs=require('fs'),path=require('path'),e2e=require('./ui_e2e_helper.cjs');
(async()=>{
 const browser=await e2e.chromium.launch({executablePath:e2e.requireBrowser(),headless:true});
 const out=process.argv[3];fs.mkdirSync(out,{recursive:true});const checks=[];
 const p=await browser.newPage({viewport:{width:1366,height:900}}),errors=[];
 p.on('pageerror',e=>errors.push(e.message));p.on('dialog',d=>d.accept());
 // Exercise the missing optional component branch independently of a source tts_bundle.
 await p.route('**/api/localtts/component',r=>r.fulfill({json:{connected:false,serviceState:'stopped',message:'尚未连接外置配音组件；历史音频仍可使用'}}));
 try{
  await p.goto(process.argv[2]);await p.locator('#boot-overlay').waitFor({state:'hidden'});
  await p.locator('#nav-tools').click();assert.equal(await p.locator('#tools-page .tool-card').count(),4);
  assert(!(await p.locator('#tools-page').innerText()).includes('语音配音'));
  await p.screenshot({path:path.join(out,'toolbox.png')});checks.push('Creation and existing-work toolbox entries');
  await p.locator('#settings-button').click();await p.locator('#open-localtts').click();
  await p.locator('#tts-component-info').waitFor({state:'visible'});await p.locator('#tts-back').click();assert(await p.locator('#settings-list').isVisible());checks.push('Optional voice entry in settings');
  await p.locator('#nav-tools').click();await p.locator('#open-roughcut').click();
  assert.equal(await p.locator('#roughcut-page h2').innerText(),'剪映草稿自动生成');
  await p.locator('#studio-text').click();assert.equal(await p.locator('.text-bulk-dialog[open]').count(),0);
  assert.equal(await p.evaluate(()=>cutEditor.snapshot().textClips.length),0);
  assert.equal(await p.locator('#draft-legacy-notice').isVisible(),false);
  const bg=await p.evaluate(async()=>(await cutEditor.api('/api/backgrounds')).items.find(v=>v.kind==='image').id);
  await p.evaluate(id=>cutEditor.applyTimeline({name:'普通素材文字界面',width:1920,height:1080,fps:30,scenes:[{background:id,duration:4,actors:[]}],textClips:[],audioClips:[]}),bg);
  await p.locator('#editor-add-text').click();await p.locator('#text-content').fill('普通评测标题');await p.locator('#text-content').press('Tab');
  assert.equal(await p.evaluate(()=>cutEditor.snapshot().textClips[0].character),'');
  assert.equal(await p.evaluate(()=>cutEditor.snapshot().scriptPlan.rows.length),0);
  assert.equal(await p.locator('.editor-lane[data-lane=actor]').count(),0);
  assert.equal(await p.locator('#dialogue-scenes').isVisible(),false);
  await p.locator('#cut-save').click();await p.waitForFunction(()=>document.querySelector('#cut-status').textContent.includes('已保存'));
  const ordinary=await p.evaluate(()=>structuredClone(cutEditor.snapshot()));
  await p.locator('#editor-undo').click();assert.notEqual(await p.evaluate(()=>cutEditor.snapshot().textClips[0]?.text),'普通评测标题');
  await p.locator('#editor-redo').click();assert.equal(await p.evaluate(()=>cutEditor.snapshot().textClips[0].text),'普通评测标题');
  await p.evaluate(async id=>cutEditor.restore(await cutEditor.api('/api/roughcut/project?id='+id)),ordinary.id);
  assert.equal(await p.evaluate(()=>cutEditor.snapshot().textClips[0].id),ordinary.textClips[0].id);
  await p.locator('#cut-export').click();await p.waitForFunction(()=>document.querySelector('#cut-status').textContent.includes('已生成'));
  checks.push('Ordinary text without script or person, undo/redo, save/reopen, export');
  await p.locator('[data-text-index="0"]').click();await p.locator('#editor-voice-tab').click();
  await p.waitForFunction(()=>document.querySelector('#voice-component-info').textContent.includes('未连接'));
  assert(await p.locator('#voice-component-open').isVisible());const beforeSettings=await p.evaluate(()=>JSON.stringify(cutEditor.snapshot()));await p.locator('#voice-component-open').click();await p.locator('#tts-component-info').waitFor({state:'visible'});await p.locator('#tts-back').click();assert(await p.locator('#roughcut-page').isVisible());assert.equal(await p.evaluate(()=>JSON.stringify(cutEditor.snapshot())),beforeSettings);checks.push('Selected text retains optional voice controls');
  if(process.argv.includes('--entry-only')){
   assert.deepEqual(errors,[]);
   await p.screenshot({path:path.join(out,'frozen-entry.png')});
   fs.writeFileSync(path.join(out,'report.json'),JSON.stringify({passed:true,checks,pageErrors:errors,scope:'Frozen entry and ordinary text; historical take checks executed separately in source UI'},null,2));
   console.log(checks.join('\n'));return;
  }
  //Reuse an existing voice take to test playback and application without running inference.
  const take=await p.evaluate(async()=>{const h=await cutEditor.api('/api/localtts/history');return h.items.find(t=>t.timelineTarget?.id);});
  assert(take);
  await p.evaluate(async ({bg,take})=>cutEditor.applyTimeline(await cutEditor.api('/api/roughcut/save',{name:'已有配音界面',width:1920,height:1080,fps:30,scenes:[{background:bg,duration:6,actors:[]}],audioClips:[],textClips:[{id:take.timelineTarget.id,text:take.timelineTarget.displayText,character:take.timelineTarget.character,start:0,duration:6}]})),{bg,take});
  await p.locator('[data-text-index="0"]').click();await p.locator('#editor-voice-tab').click();
  await p.waitForFunction(()=>document.querySelector('#voice-takes').options.length>1);
  await p.locator('#voice-player').evaluate(a=>a.play());await p.waitForFunction(()=>document.querySelector('#voice-player').duration>0);
  const original=await p.evaluate(()=>JSON.stringify(cutEditor.snapshot()));
  await p.locator('#voice-mode').selectOption('keep');await p.locator('#voice-preview').click();await p.locator('#voice-apply').waitFor({state:'visible'});
  assert.equal(await p.evaluate(()=>JSON.stringify(cutEditor.snapshot())),original);
  assert((await p.locator('#voice-impact').innerText()).includes('完整配音'));
  await p.locator('#voice-apply').click();await p.waitForFunction(()=>cutEditor.snapshot().audioClips.length===1);
  assert.equal(await p.evaluate(()=>cutEditor.snapshot().textClips[0].duration),6);
  await p.locator('#editor-undo').click();assert.equal(await p.evaluate(()=>cutEditor.snapshot().audioClips.length),0);
  await p.locator('#editor-redo').click();assert.equal(await p.evaluate(()=>cutEditor.snapshot().audioClips.length),1);
  checks.push('Existing audio plays without component; preview does not apply; explicit apply and undo');
  await p.screenshot({path:path.join(out,'ordinary-1366.png')});
  //Preserve a stale script marker and use the real preflight button to resolve it.
  await p.evaluate(async bg=>{const plan=await cutEditor.api('/api/script/import',{text:'旧项目计时文字'});const normalized=await cutEditor.api('/api/roughcut/save',{name:'旧计时兼容',scenes:[{background:bg,duration:4}],scriptPlan:plan.plan||plan});normalized.scriptTiming={plan:structuredClone(normalized.scriptPlan)};normalized.scriptPlan.rows[0].text='待重新核对的旧文字';cutEditor.restore(normalized);},bg);
  assert(await p.locator('#draft-legacy-notice').isVisible());
  assert.equal(await p.locator('#studio-script').isVisible(),false);
  await p.locator('#editor-preflight summary').click();
  await p.locator('#editor-preflight-list button').filter({hasText:'重新计算并铺轨'}).click();
  await p.locator('#script-dialog').waitFor({state:'visible'});
  await p.waitForFunction(()=>document.querySelector('#script-dialog').dataset.loading==='false');
  assert.equal(await p.locator('#script-import-file').isVisible(),false);
  assert.equal(await p.evaluate(()=>cutEditor.snapshot().scriptTiming.plan.rows[0].text),'旧项目计时文字');
  await p.locator('#script-close').click();await p.locator('#draft-open-legacy').click();await p.locator('#script-dialog').waitFor({state:'visible'});await p.locator('#script-close').click();
  checks.push('Legacy timing retained, stale marker protected and compatibility entry operable');
  await p.locator('#studio-project-settings').click();await p.locator('#cut-new').click();await p.locator('#studio-project-close').click();
  assert.equal(await p.locator('#draft-legacy-notice').isVisible(),false);
  assert.equal(await p.evaluate(()=>cutEditor.snapshot().scriptTiming),undefined);
  await p.evaluate(async id=>cutEditor.restore(await cutEditor.api('/api/roughcut/save',{name:'普通草稿',width:1920,height:1080,fps:30,scenes:[{background:id,duration:4}],textClips:[{text:'普通标题',character:'',start:0,duration:4}],audioClips:[]})),bg);
  await p.setViewportSize({width:1920,height:1080});await p.screenshot({path:path.join(out,'ordinary-1920.png')});
  assert.deepEqual(errors,[]);fs.writeFileSync(path.join(out,'report.json'),JSON.stringify({passed:true,checks,pageErrors:errors},null,2));console.log(checks.join('\n'));
 }catch(err){await p.screenshot({path:path.join(out,'failure.png')});console.log(await p.locator('#cut-status').textContent());throw err;}finally{await browser.close();}
})().catch(err=>{console.error(err);process.exitCode=1;});
