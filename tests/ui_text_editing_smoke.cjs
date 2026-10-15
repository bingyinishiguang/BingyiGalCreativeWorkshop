const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),e2e=require('./ui_e2e_helper.cjs');
(async()=>{
 const browser=await e2e.chromium.launch({executablePath:e2e.requireBrowser(),headless:true}),page=await browser.newPage({viewport:{width:1366,height:900}}),out=process.argv[3],errors=[];
 if(out)fs.mkdirSync(out,{recursive:true});page.on('pageerror',error=>errors.push(error.message));page.on('dialog',dialog=>dialog.accept());
 const snapshot=()=>page.evaluate(()=>structuredClone(cutEditor.snapshot()));
 const open=async()=>{await page.locator('#boot-overlay').waitFor({state:'hidden'});await page.locator('#nav-tools').click();await page.locator('#open-roughcut').click();};
 const save=async()=>{await page.locator('#cut-save').click();await page.waitForFunction(()=>!cutEditor.isBusy()&&!cutEditor.isDirty()&&document.querySelector('#cut-status').textContent.includes('已保存'));};
 try{
  await page.goto(process.argv[2]);await open();await page.locator('#studio-project-settings').click();await page.locator('#cut-new').click();await page.locator('#studio-project-close').click();
  await page.locator('#studio-text').click();await page.locator('#studio-add-default-text').focus();await page.keyboard.press('Space');
  assert.equal((await snapshot()).textClips.length,1,'Space must activate a focused button');
  await page.locator('#text-content').fill('第一句');await page.locator('#text-content').press('Tab');await save();
  const original=await snapshot();await page.locator('#text-copy').click();const copied=await snapshot();
  assert.equal(copied.textClips.length,2);assert.notEqual(copied.textClips[0].id,copied.textClips[1].id);assert.equal(copied.textClips[1].start,3);
  assert.equal(await page.locator('.editor-segment.text.selected').getAttribute('data-text-index'),'1');assert.equal(await page.locator('#dialogue-preview-time').inputValue(),'3.000');assert(await page.locator('#text-content').evaluate(node=>document.activeElement===node));
  assert.equal(await page.locator('.standalone-text').textContent(),'第一句');
  await page.locator('#editor-undo').click();assert.deepEqual((await snapshot()).textClips,original.textClips);assert.deepEqual((await snapshot()).scenes,original.scenes);
  await page.locator('#editor-redo').click();assert.deepEqual((await snapshot()).textClips,copied.textClips);assert.deepEqual((await snapshot()).scenes,copied.scenes);
  await page.locator('[data-text-index="1"]').click();await save();const clean=await snapshot();
  await page.locator('#text-content').fill('   ');await page.locator('#text-content').press('Tab');assert.equal(await page.locator('#text-content').inputValue(),'第一句');assert((await page.locator('#text-status').textContent()).includes('文字不能为空'));assert.deepEqual(await snapshot(),clean);assert.equal(await page.evaluate(()=>cutEditor.isDirty()),false);
  await page.locator('#text-content').fill('第二句');await page.locator('#text-content').press('Tab');assert.equal(await page.locator('#text-status').textContent(),'');assert.equal((await snapshot()).textClips[1].text,'第二句');assert.equal(await page.locator('.standalone-text').textContent(),'第二句');await save();
  const saved=await snapshot();await page.reload();await open();await page.locator('#studio-project-settings').click();await page.locator('#cut-projects').selectOption(saved.id);await page.waitForFunction(()=>document.querySelector('#cut-status').textContent.includes('已打开'));await page.locator('#studio-project-close').click();assert.deepEqual((await snapshot()).textClips,saved.textClips);
  await page.locator('[data-text-index="1"]').click();assert.equal(await page.locator('#text-content').inputValue(),'第二句');assert.equal(await page.locator('.standalone-text').textContent(),'第二句');assert.deepEqual(errors,[]);
  if(out){await page.screenshot({path:path.join(out,'text-editing.png')});fs.writeFileSync(path.join(out,'report.json'),JSON.stringify({passed:true,checks:['copy selects/seeks/focuses','single undo/redo includes coverage','empty restores without dirty','valid input clears message','real save/reopen'],pageErrors:errors},null,2));}
  console.log('PASS: copy selection/seek/focus, one undo/redo, empty-input feedback without dirty, valid text and save/reopen');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
