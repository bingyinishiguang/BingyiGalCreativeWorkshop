const assert=require('node:assert/strict'),fs=require('fs'),path=require('path'),e2e=require('./ui_e2e_helper.cjs');
(async()=>{
 const browser=await e2e.chromium.launch({executablePath:e2e.requireBrowser(),headless:true});
 const p=await browser.newPage({viewport:{width:1366,height:900}}),errors=[];p.on('pageerror',e=>errors.push(e.message));
 const out=process.argv[3];fs.mkdirSync(out,{recursive:true});
 try{
  await p.goto(process.argv[2]);await p.locator('#boot-overlay').waitFor({state:'hidden'});
  assert((await p.request.post(new URL('/api/localtts/start',process.argv[2]).href,{data:{}})).ok());
  const readyUntil=Date.now()+180000;let ready=false;
  while(Date.now()<readyUntil){const response=await p.request.post(new URL('/api/localtts/test',process.argv[2]).href,{data:{}});if(response.ok()&&(await response.json()).ok){ready=true;break;}await new Promise(resolve=>setTimeout(resolve,3000));}
  assert(ready,'local inference did not become ready');
  await p.locator('#nav-tools').click();await p.locator('#open-roughcut').click();
  await p.locator('#studio-script').click();
  await p.route('**/api/script/pick',r=>r.fulfill({json:{paths:[path.resolve(process.argv[4])]}}));
  await p.locator('#script-import-file').click();await p.waitForFunction(()=>document.querySelectorAll('#script-rows tr').length===6);
  assert.deepEqual(await p.evaluate(()=>cutScript.snapshot().scriptPlan.rows.map(r=>r.kind)),['narrator','inner','dialogue','dialogue','dialogue','narrator']);
  assert.equal(await p.locator('#script-rows tr').first().locator('[data-field=kind] option').count(),3);
  assert.equal(await p.locator('#script-rows tr').nth(4).locator('[data-field=voice]').isChecked(),false);
  await p.locator('#script-save').click();await p.waitForFunction(()=>document.querySelector('#script-status').textContent.includes('独立剧本已保存'));
  assert((await p.locator('#script-drafts option').count())>1);
  await p.locator('#script-close').click();await p.locator('#cut-assets [data-add-asset]').first().click();await p.locator('#studio-script').click();await p.waitForFunction(()=>document.querySelector('#script-dialog').dataset.loading==='false');
  await p.locator('#script-capture-voice').click();await p.waitForFunction(()=>document.querySelector('#script-rule-preset').options.length>1);
  await p.locator('#script-voice-rules summary').click();await p.locator('#script-rule-character').selectOption('莉莉子');
  await p.locator('#script-rule-preset').selectOption({index:1});await p.locator('#script-rule-language').selectOption('zh');await p.locator('#script-rule-apply').click();
  await p.locator('#script-rows tr').last().locator('[data-review]').check();
  const waitDone=()=>p.waitForFunction(()=>document.querySelector('#script-batch-status').textContent.includes('已绑定台词'),{},{timeout:240000});
  await p.locator('#script-batch-generate').click();await p.waitForFunction(()=>document.querySelector('#script-batch-generate').disabled);await waitDone();
  let plan=await p.evaluate(()=>structuredClone(cutScript.snapshot().scriptPlan));
  assert(plan.rows[2].audio&&plan.rows[3].audio);assert(!plan.rows[0].audio&&!plan.rows[1].audio&&!plan.rows[4].audio);
  assert.equal(plan.directives.length,2);
  await p.locator('#script-rows tr').nth(2).locator('[data-action=listen]').click();await p.waitForFunction(()=>document.querySelector('#script-audition').duration>0&&!document.querySelector('#script-audition').paused);
  await p.locator('#script-rows tr').nth(2).locator('[data-generate-one]').click();await p.waitForFunction(()=>document.querySelector('#script-batch-generate').disabled);await waitDone();
  plan=await p.evaluate(()=>structuredClone(cutScript.snapshot().scriptPlan));assert.equal(plan.rows[2].versions.length,2);
  const versions=p.locator('#script-rows tr').nth(2).locator('[data-take]');await versions.selectOption({index:0});
  await p.waitForFunction(()=>cutScript.snapshot().scriptPlan.rows[2].take===cutScript.snapshot().scriptPlan.rows[2].versions[0]);
  await p.locator('#script-save').click();await p.waitForFunction(()=>document.querySelector('#cut-status').textContent.includes('已保存'));
  const id=await p.evaluate(()=>cutEditor.snapshot().id);
  await p.screenshot({path:path.join(out,'script-review-1366.png')});
  await p.locator('#script-close').click();await p.reload();await p.locator('#boot-overlay').waitFor({state:'hidden'});await p.locator('#nav-tools').click();await p.locator('#open-roughcut').click();
  await p.locator('#studio-project-settings').click();await p.locator('#cut-projects').selectOption(id);await p.locator('#studio-project-close').click();await p.locator('#studio-script').click();await p.waitForFunction(()=>document.querySelector('#script-dialog').dataset.loading==='false');
  assert.equal(await p.evaluate(()=>cutScript.snapshot().scriptPlan.rows[2].versions.length),2);
  assert.equal(await p.evaluate(()=>cutScript.snapshot().scriptPlan.rows[5].reviewed),true);
  await p.locator('#script-rows tr').nth(2).locator('[data-field=text]').fill('修改后的台词，旧音频需要重新核对。');await p.locator('#script-rows tr').nth(2).locator('[data-field=text]').press('Tab');
  assert(await p.locator('#script-rows tr').nth(2).locator('.script-audio-warning').isVisible());
  await p.locator('#script-jobs-refresh').click();await p.waitForFunction(()=>document.querySelectorAll('#script-jobs article').length>=2);
  await p.setViewportSize({width:1920,height:1080});await p.screenshot({path:path.join(out,'script-review-1920.png')});
  assert.deepEqual(errors,[]);console.log('PASS: TXT import, three categories, role preset, real batch inference, single regeneration, version choice, save/reopen, stale audio warning');
 }catch(error){await p.screenshot({path:path.join(out,'failure.png')});console.log(await p.locator('#script-batch-status').textContent());throw error;}finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
