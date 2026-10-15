// Self-contained browser fixture: no TTS models or personal project data needed.
const assert=require('node:assert/strict'),path=require('node:path'),e2e=require('./ui_e2e_helper.cjs');
(async()=>{
 const browser=await e2e.chromium.launch({executablePath:e2e.requireBrowser(),headless:true});
 const page=await browser.newPage(),errors=[];page.on('pageerror',error=>errors.push(error.message));
 try{
  async function load(){
   await page.setContent('<main id="roughcut-page"><div class="production-heading"></div><div class="editor-property-tabs"></div><div class="cut-inspector"></div></main>');
   await page.evaluate(()=>{
    window.fixture={project:{id:'project1',textClips:[{id:'text1',text:'测试台词',character:'角色',start:0,duration:3}]},jobs:[],calls:[],applied:0,offline:false};
    window.cutEditor={escape:text=>String(text).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),snapshot:()=>fixture.project,applyTimeline:()=>fixture.applied++,api:async(url,payload)=>{
     fixture.calls.push({url,payload});if(fixture.offline&&url.includes('/jobs'))throw Error('连接已断开');
     if(url==='/api/localtts/component')return{connected:true,message:'已连接'};
     if(url==='/api/localtts/voices')return{items:[{id:'voice1',ready:true,name:'声音',preset:{name:'声音',textLanguage:'zh',speed:1}}]};
     if(url.includes('/history'))return{items:fixture.jobs.filter(j=>j.result).map(j=>j.result)};
     if(url==='/api/timeline-voice/jobs'&&payload){const job={id:'job'+(fixture.jobs.length+1),status:'queued',createdAt:Date.now()/1000,updatedAt:Date.now()/1000,error:'',result:null,projectId:payload.project.id,binding:{id:payload.target,displayText:payload.project.textClips[0].text,character:'角色'}};fixture.jobs.push(job);return job;}
     if(url==='/api/timeline-voice/jobs')return{items:structuredClone(fixture.jobs)};
     if(url.includes('/job?id='))return structuredClone(fixture.jobs.find(j=>j.id===url.split('=').at(-1)));
     if(url.endsWith('/job-stop')){fixture.jobs.find(j=>j.id===payload.id).status='stopped';return{};}
     if(url.endsWith('/job-resume')){fixture.jobs.find(j=>j.id===payload.id).status='running';return{};}
     throw Error('Unexpected API '+url);
    }};
    window.cutV2={loadAudio:async()=>{},stopPlayback:()=>{}};window.cutText={select:index=>window.dispatchEvent(new CustomEvent('cut-text-selected',{detail:{index}}))};window.switchPage=()=>{};
   });
   await page.addScriptTag({path:path.resolve(__dirname,'../ui/timeline_voice.js')});
  }
  await load();await page.evaluate(()=>cutText.select(0));await page.waitForFunction(()=>document.querySelector('#voice-profile').value==='voice1');
  await page.evaluate(()=>document.querySelector('#editor-voice-properties').hidden=false);
  await page.locator('#voice-generate').click();await page.waitForFunction(()=>fixture.jobs.length===1&&!document.querySelector('#voice-generate').disabled);
  assert.equal(await page.evaluate(()=>fixture.applied),0);assert.equal(await page.locator('[data-job-action=stop]').count(),1);
  assert(await page.locator('#voice-jobs-open').textContent().then(text=>text.includes('处理中')));
  assert(await page.locator('#voice-jobs-list').textContent().then(text=>text.includes('排队中')));
  assert.equal(await page.evaluate(()=>Object.hasOwn(fixture.jobs[0],'state')),false);
  await page.evaluate(()=>{fixture.jobs[0].status='running';});await page.locator('#voice-jobs-refresh').click();await page.waitForFunction(()=>document.querySelector('#voice-jobs-list').textContent.includes('生成中'));
  await page.evaluate(()=>window.dispatchEvent(new CustomEvent('workshop-page',{detail:'localtts'})));
  await page.evaluate(()=>{fixture.jobs[0].status='failed';fixture.jobs[0].error='推理服务不可用';window.dispatchEvent(new CustomEvent('workshop-page',{detail:'roughcut'}));});
  await page.waitForFunction(()=>document.querySelector('#voice-jobs-list').textContent.includes('推理服务不可用'));
  await page.locator('[data-job-action=view]').click();assert.equal(await page.locator('#voice-jobs-status').textContent(),'推理服务不可用');
  await page.locator('[data-job-action=resume]').click();await page.waitForFunction(()=>fixture.jobs[0].status==='running');
  await page.locator('[data-job-action=stop]').click();await page.waitForFunction(()=>document.querySelector('[data-job-action=resume]'));
  assert(await page.locator('#voice-jobs-list').textContent().then(text=>text.includes('已停止')));
  await page.evaluate(()=>{fixture.jobs[0].status='interrupted';});await page.locator('#voice-jobs-refresh').click();await page.waitForFunction(()=>document.querySelector('#voice-jobs-list').textContent.includes('已中断'));assert.equal(await page.locator('[data-job-action=resume]').count(),1);
  await page.evaluate(()=>{fixture.offline=true;});await page.locator('#voice-jobs-refresh').click();await page.waitForFunction(()=>document.querySelector('#voice-jobs-status').textContent.includes('恢复连接'));
  await page.evaluate(()=>{fixture.offline=false;const j=fixture.jobs[0];j.status='complete';j.result={id:'take1',timelineTarget:j.binding,preset:{name:'声音'},duration:2,created:new Date().toISOString()};});
  await page.locator('#voice-jobs-refresh').click();await page.waitForFunction(()=>document.querySelector('#voice-jobs-list').textContent.includes('试听'));
  await page.locator('[data-job-action=view]').click();await page.waitForFunction(()=>document.querySelector('#voice-takes').value==='take1');assert.equal(await page.evaluate(()=>fixture.applied),0);
  await page.evaluate(()=>{fixture.project.textClips[0].text='已修改台词';});await page.locator('[data-job-action=view]').click();await page.waitForFunction(()=>document.querySelector('#voice-jobs-status').textContent.includes('不能直接应用'));
  assert(await page.locator('#voice-job-player').isVisible());assert(await page.locator('#voice-apply').isHidden());
  await page.evaluate(()=>{fixture.project.textClips[0].text='测试台词';fixture.project.id='other-project';});await page.locator('[data-job-action=view]').click();await page.waitForFunction(()=>document.querySelector('#voice-jobs-status').textContent.includes('不能直接应用'));
  // Simulate reopening the UI against durable API records, rather than browser memory.
  const saved=await page.evaluate(()=>structuredClone(fixture.jobs));await page.goto('about:blank');await load();await page.evaluate(jobs=>{fixture.jobs=jobs;},saved);await page.locator('#voice-jobs-open').click();await page.waitForFunction(()=>document.querySelector('[data-voice-job="job1"]'));
  assert.deepEqual(errors,[]);console.log('PASS: background submit, page return, stop/resume, failed service, reconnect, safe completed audition, stale/project guard, reopened records');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
