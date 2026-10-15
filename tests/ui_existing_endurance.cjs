/* Bounded long-draft UI endurance. Uses disposable fixtures and local APIs. */
const fs=require('fs'),path=require('path'),assert=require('assert/strict'),crypto=require('crypto');
const {chromium,requireBrowser}=require('./ui_e2e_helper.cjs');
const {expect}=require(path.join(path.dirname(require.resolve(process.env.BINGYI_PLAYWRIGHT||'playwright')),'test'));
const root=path.resolve(process.env.BINGYI_RECOVERY_ROOT||'output/recovery-workbench');
const minutes=Number(process.env.BINGYI_UI_SOAK_MINUTES||25);
if(!Number.isFinite(minutes)||minutes<1||minutes>60)throw Error('Bounded duration required');
const fixtureFolder=path.join(root,'large-fixture-'+Date.now());fs.mkdirSync(fixtureFolder,{recursive:true});
const fixture=path.join(fixtureFolder,'draft_content.json');
require('./ui_draft_fixture.cjs').createDraftFixture(fixture);
const data=JSON.parse(fs.readFileSync(fixture,'utf8'));
const baseMaterial=structuredClone(data.materials.texts[0]),baseSegment=structuredClone(data.tracks[1].segments[0]);
data.tracks[1].segments=[];
for(let i=0;i<1000;i++){
 const text=`第 ${i+1} 条长稿验收字幕`,id='endurance-'+i;
 const material=structuredClone(baseMaterial);material.id=id;
 const content=JSON.parse(material.content);content.text=text;content.styles.forEach(style=>style.range=[0,text.length]);material.content=JSON.stringify(content);data.materials.texts.push(material);
 const segment=structuredClone(baseSegment);segment.id='endurance-segment-'+i;segment.material_id=id;segment.target_timerange={start:i*2000000,duration:2000000};data.tracks[1].segments.push(segment);
}
data.duration=2000000000;fs.writeFileSync(fixture,JSON.stringify(data));
const digest=()=>crypto.createHash('sha256').update(fs.readFileSync(fixture)).digest('hex'),originalHash=digest();
(async()=>{
 const browser=await chromium.launch({executablePath:requireBrowser(),headless:true});const context=await browser.newContext({viewport:{width:1400,height:950}});const page=await context.newPage();
 const errors=[],rounds=[];page.on('pageerror',e=>errors.push(e.message));const started=Date.now(),deadline=started+minutes*60000;
 try{
  await page.goto(fs.readFileSync(path.join(root,'preview-url.txt'),'utf8').trim(),{waitUntil:'domcontentloaded'});
  await page.locator('#nav-tools').click();await page.locator('#open-existing-draft').click();await page.locator('#existing-path').fill(fixture);await page.locator('#existing-load').click();await expect(page.locator('#existing-count')).toContainText('1000 条字幕');await page.locator('#existing-auto-save').uncheck();
  await page.locator('#existing-recovery summary').click();
  while(true){
   const round=rounds.length+1,iterationStart=Date.now(),last=page.locator('#existing-cues textarea[data-cue-index="999"]');
   await page.locator('#existing-jump').fill('1000');await page.locator('#existing-jump-go').click();await expect(page.locator('#existing-location')).toContainText('第 1000 条');
   await last.fill(`第 ${round} 轮最后一条校对`);await last.press('Tab');
   await page.locator('#existing-backup-create').click();await expect(page.locator('#existing-status')).toContainText('已备份');const backupId=await page.locator('#existing-backups option').nth(1).getAttribute('value');
   await page.locator('#existing-jump').fill('1');await page.locator('#existing-jump-go').click();const first=page.locator('#existing-cues textarea[data-cue-index="0"]');const before=await first.inputValue();await first.fill('需要通过备份找回的编辑');await first.press('Tab');
   await page.locator('#existing-backups').selectOption(backupId);await page.locator('#existing-backup-preview').click();await expect(page.locator('#existing-backup-status')).toHaveText('预览完成，尚未恢复');await expect(first).toHaveValue('需要通过备份找回的编辑');
   await page.locator('#existing-backup-apply').click();await expect(first).toHaveValue(before);await page.locator('#existing-undo').click();await expect(first).toHaveValue('需要通过备份找回的编辑');await page.locator('#existing-redo').click();await expect(first).toHaveValue(before);
   await page.locator('#existing-track').selectOption('2');await page.locator('#existing-cues textarea').first().fill(`独立轨道第 ${round} 轮`);await page.locator('#existing-cues textarea').first().press('Tab');await page.locator('#existing-track').selectOption('1');await expect(last).toHaveValue(`第 ${round} 轮最后一条校对`);
   await page.locator('#existing-progress-save').click();await expect(page.locator('#existing-progress-status')).toHaveText('进度已保存');
   if(round%5===0){await page.evaluate(()=>document.querySelector('#existing-source').open=true);await page.locator('#existing-load').click();await expect(page.locator('#existing-status')).toContainText('已恢复保存的编辑进度');await expect(last).toHaveValue(`第 ${round} 轮最后一条校对`);}
   assert.equal(digest(),originalHash);assert.equal(errors.length,0);
   const memory=await page.evaluate(()=>({domNodes:document.querySelectorAll('*').length,heapBytes:performance.memory?.usedJSHeapSize||null}));
   const elapsed=Date.now()-started;rounds.push({round,elapsedSeconds:elapsed/1000,operationSeconds:(Date.now()-iterationStart)/1000,...memory,sourceUnchanged:true});
   const report={status:Date.now()>=deadline?'passed':'running',cueCount:1000,externalAPIRequests:0,sourceHash:originalHash,rounds,pageErrors:errors};fs.writeFileSync(path.join(root,'ui-endurance.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(rounds.at(-1)));
   if(report.status==='passed')break;
   await new Promise(resolve=>setTimeout(resolve,Math.min(60000,Math.max(0,deadline-Date.now()))));
  }
 }finally{await browser.close();}
})().catch(error=>{const reportPath=path.join(root,'ui-endurance.json');let report={};try{report=JSON.parse(fs.readFileSync(reportPath,'utf8'));}catch{}report.status='failed';report.error=error.message;fs.writeFileSync(reportPath,JSON.stringify(report,null,2));console.error(error);process.exitCode=1;});
