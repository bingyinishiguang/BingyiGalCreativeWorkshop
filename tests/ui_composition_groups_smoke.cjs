const assert=require('node:assert/strict'),fs=require('fs'),path=require('path'),e2e=require('./ui_e2e_helper.cjs');
(async()=>{
 const browser=await e2e.chromium.launch({executablePath:e2e.requireBrowser(),headless:true});
 const out=process.argv[3];fs.mkdirSync(out,{recursive:true});
 try{
  const p=await browser.newPage({viewport:{width:1920,height:1080}}),errors=[];
  p.on('pageerror',e=>errors.push(e.message));p.on('dialog',d=>d.accept(d.type()==='prompt'?'横屏半身构图':undefined));
  await p.goto(process.argv[2]);await p.locator('#boot-overlay').waitFor({state:'hidden'});
  await p.locator('#nav-tools').click();await p.locator('#open-roughcut').click();
  await p.locator('#cut-assets [data-add-asset]').first().click();await p.locator('#cut-sprite-tab').click();
  const fixtureIds=await p.evaluate(async()=>{const data=await cutEditor.api('/api/library?limit=500');return data.items.filter(item=>item.game==='自制验收素材'&&item.width===400&&item.height===700).map(item=>item.id);});
  assert(fixtureIds.length>=2,'Start the isolated preview with its synthetic sprite library');
  const cards=p.locator(fixtureIds.slice(0,2).map(id=>`#cut-assets .production-tile[data-asset-id="${id}"]`).join(','));
  await cards.first().waitFor();assert(await cards.first().locator('.expression-pick').isHidden());
  await p.locator('#cut-create-group').click();assert(await p.locator('#cut-create-group').isDisabled());
  await cards.first().locator('.expression-pick input').check();await cards.nth(1).locator('.expression-pick input').check();
  assert((await p.locator('#expression-selection-count').textContent()).includes('已选 2 张'));
  await p.locator('#cut-asset-search').fill('测试人物');await p.locator('#cut-asset-search').press('Enter');
  await p.waitForFunction(()=>document.querySelectorAll('.expression-pick input:checked').length===2);
  await p.locator('#cut-create-group').click();await p.locator('#expression-dialog').waitFor({state:'visible'});
  await p.locator('#group-next').click();await p.screenshot({path:path.join(out,'group-calibration.png')});
  await p.locator('#group-save').click();await p.locator('#expression-dialog').waitFor({state:'hidden'});
  assert(await p.locator('#expression-selection-bar').isHidden());assert(await cards.first().locator('.expression-pick').isHidden());
  await cards.first().locator('[data-add-asset]').click();await p.locator('#actor-expression-group').waitFor();
  const groupId=await p.locator('#actor-expression-group option').nth(1).getAttribute('value');
  await p.locator('#actor-expression-group').selectOption(groupId);
  const edit=async(id,v)=>{await p.locator('#'+id).fill(String(v));await p.locator('#'+id).press('Tab');};
  await edit('cut-scale',170);await edit('cut-position-x',90);await edit('cut-position-y',-280);
  const first=await p.evaluate(()=>cutEditor.snapshot().scenes[0].actors[0]);assert.equal(first.transform.x,90);assert.equal(first.transform.y,-280);
  const next=await p.locator('#actor-expression option').evaluateAll((o,id)=>o.find(x=>x.value!==id).value,first.id);
  await p.locator('#actor-expression').selectOption(next);
  const second=await p.evaluate(()=>cutEditor.snapshot().scenes[0].actors[0]);
  assert.notEqual(second.id,first.id);assert.deepEqual(second.transform,first.transform);assert.equal(second.alignment.width,400);assert.equal(second.alignment.height,700);
  await p.locator('#cut-preset-tab').click();await p.locator('#save-composition-preset').click();await p.waitForFunction(()=>document.querySelector('#cut-status').textContent==='构图预设已保存');
  await p.locator('#composition-preset-list .composition-preset').filter({hasText:'横屏半身构图'}).last().waitFor();
  await p.locator('#studio-project-settings').click();await p.locator('#cut-canvas').selectOption('1080x1920');await p.locator('#studio-project-close').click();assert.equal(await p.locator('#composition-preset-list .composition-preset').count(),0);
  await p.locator('#studio-project-settings').click();await p.locator('#cut-canvas').selectOption('1920x1080');await p.locator('#studio-project-close').click();await p.locator('#cut-visual-target').selectOption('0');await edit('cut-position-x',0);
  await p.locator('[data-apply-preset]').last().click();await p.waitForFunction(()=>cutEditor.snapshot().scenes[0].actors[0].transform.x===90);
  await p.locator('#cut-save').click();await p.waitForFunction(()=>document.querySelector('#cut-status').textContent.includes('已保存'));
  const id=await p.evaluate(()=>cutEditor.snapshot().id);await p.reload();await p.locator('#boot-overlay').waitFor({state:'hidden'});
  await p.locator('#nav-tools').click();await p.locator('#open-roughcut').click();await p.locator('#studio-project-settings').click();await p.locator('#cut-projects').selectOption(id);await p.locator('#studio-project-close').click();await p.waitForFunction(()=>document.querySelector('#cut-status').textContent.includes('已打开'));
  const reopened=await p.evaluate(()=>cutEditor.snapshot().scenes[0].actors[0]);assert.deepEqual(reopened.alignment,second.alignment);assert.deepEqual(reopened.transform,second.transform);
  await p.locator('#cut-visual-target').selectOption('0');await p.locator('#cut-export').click();await p.waitForFunction(()=>document.querySelector('#cut-status').textContent.includes('已生成'));
  await p.locator('#cut-preset-tab').click();await p.screenshot({path:path.join(out,'presets-1920.png')});
  await p.setViewportSize({width:1366,height:768});await p.screenshot({path:path.join(out,'presets-1366.png')});
  assert.equal(errors.length,0,errors.join('\n'));const report={groupId,groupSize:[400,700],stableTransform:true,ratioIsolation:true,presetApplied:true,reopened:true,exported:true,pageErrors:errors};fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
 }catch(error){console.log(await browser.contexts()[0].pages()[0].evaluate(()=>({status:document.querySelector('#cut-status')?.textContent,groupError:document.querySelector('#group-error')?.textContent})));throw error;}
 finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
