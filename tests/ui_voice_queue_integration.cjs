const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium,requireBrowser}=require('./ui_e2e_helper.cjs');
(async()=>{
 const out=path.resolve(process.argv[3]);fs.mkdirSync(out,{recursive:true});
 const browser=await chromium.launch({executablePath:requireBrowser(),headless:true}),page=await browser.newPage({viewport:{width:1366,height:900}}),errors=[];
 page.on('pageerror',error=>errors.push(error.message));
 try{
  await page.goto(process.argv[2]);await page.locator('#boot-overlay').waitFor({state:'hidden'});await page.locator('#nav-tools').click();await page.locator('#open-roughcut').click();
  const reuse=process.argv[4]==='--reuse'?await page.evaluate(async()=>(await cutEditor.api('/api/timeline-voice/jobs')).items.find(j=>j.status==='complete')):null;
  await page.evaluate(async reuse=>{const bg=(await cutEditor.api('/api/backgrounds')).items.find(v=>v.kind==='image');cutEditor.applyTimeline({name:'后台配音测试',width:1920,height:1080,fps:30,scenes:[{background:bg.id,duration:3,actors:[]}],textClips:[{id:reuse?.binding.id||crypto.randomUUID().replaceAll('-',''),text:'后台配音测试。',character:'测试角色',start:0,duration:3,track:0,subtitleStyle:{x:0,y:-.8,size:8,color:'#ffffff',borderColor:'#000000',borderWidth:40,showCharacter:false}}],audioClips:[]});},reuse);
  await page.locator('[data-text-index="0"]').click();await page.locator('#editor-voice-tab').click();
  await page.waitForFunction(()=>document.querySelector('#voice-profile').options.length>1);
  await page.locator('#voice-spoken').fill('早上好。');await page.locator('#voice-sample-steps').selectOption('16');
  if(!reuse){await page.locator('#voice-generate').click();await page.waitForFunction(()=>document.querySelector('#voice-status').textContent.includes('已提交后台配音'));}
  assert.equal(await page.evaluate(()=>cutEditor.snapshot().audioClips.length),0);
  const target=await page.evaluate(()=>cutEditor.snapshot().textClips[0].id);
  await page.locator('#cut-back').click();await page.locator('#open-roughcut').click();
  const started=Date.now();
  let completedJob=null;const deadline=Date.now()+420000;
  while(Date.now()<deadline){const data=await page.evaluate(()=>cutEditor.api('/api/timeline-voice/jobs'));const current=data.items.find(j=>j.binding?.id===target);if(current?.status==='failed')throw Error(current.error);if(current?.status==='complete'){completedJob=current;break;}await new Promise(resolve=>setTimeout(resolve,1000));}
  assert(completedJob,'background inference did not finish');
  await page.locator('#voice-jobs-open').click();await page.locator('#voice-jobs-refresh').click();const data=await page.evaluate(()=>cutEditor.api('/api/timeline-voice/jobs'));const completed=data.items.find(j=>j.binding?.id===target);const job=page.locator(`[data-voice-job="${completed.id}"]`);await job.locator('[data-job-action="view"]').click();
  await page.waitForTimeout(700);
  if(!(await page.locator('#voice-takes').inputValue()))console.log(JSON.stringify(await page.evaluate(()=>({status:document.querySelector('#voice-status').textContent,jobs:document.querySelector('#voice-jobs-status').textContent,clips:cutEditor.snapshot().textClips.map(c=>({id:c.id,text:c.text})),options:[...document.querySelector('#voice-takes').options].map(o=>o.value)}))));
  await page.waitForFunction(()=>document.querySelector('#voice-takes').value.length>0);await page.locator('#voice-preview').click();await page.locator('#voice-apply').waitFor({state:'visible'});await page.locator('#voice-apply').click();
  await page.waitForFunction(()=>cutEditor.snapshot().audioClips.length===1);assert.equal(await page.evaluate(()=>cutEditor.snapshot().textClips[0].text),'后台配音测试。');
  await page.locator('#editor-undo').click();assert.equal(await page.evaluate(()=>cutEditor.snapshot().audioClips.length),0);await page.locator('#editor-redo').click();assert.equal(await page.evaluate(()=>cutEditor.snapshot().audioClips.length),1);
  await page.locator('#cut-save').click();await page.waitForFunction(()=>document.querySelector('#cut-status').textContent.includes('项目已保存'));const id=await page.evaluate(()=>cutEditor.snapshot().id);
  await page.reload();await page.locator('#boot-overlay').waitFor({state:'hidden'});await page.locator('#nav-tools').click();await page.locator('#open-roughcut').click();await page.locator('#studio-project-settings').click();await page.locator('#cut-projects').selectOption(id);await page.waitForFunction(()=>document.querySelector('#cut-status').textContent.includes('已打开'));await page.locator('#studio-project-close').click();
  assert.equal(await page.evaluate(()=>cutEditor.snapshot().audioClips.length),1);assert.deepEqual(errors,[]);await page.screenshot({path:path.join(out,'queue-applied.png')});
  const report={passed:true,generatedInThisRun:!reuse,seconds:(Date.now()-started)/1000,checks:[reuse?'completed inference result retrieval':'real background inference',reuse?'navigation with completed task':'navigation during job','manual result application','undo and redo','save and reopen'],errors};fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
