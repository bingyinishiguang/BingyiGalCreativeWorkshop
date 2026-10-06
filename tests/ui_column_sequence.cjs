const assert=require('node:assert/strict'),fs=require('fs'),path=require('path'),e2e=require('./ui_e2e_helper.cjs');
(async()=>{
 const root=process.argv[3],inputs=JSON.parse(fs.readFileSync(path.join(root,'inputs.json'),'utf8'));
 const browser=await e2e.chromium.launch({executablePath:e2e.requireBrowser(),headless:true});
 const p=await browser.newPage({viewport:{width:1366,height:1000}}),errors=[],projects=[];
 p.on('pageerror',e=>errors.push(e.message));p.on('dialog',d=>d.accept());
 const field=(i,k)=>p.locator(`[data-seq-index="${i}"][data-seq-key="${k}"]`);
 const fill=async(i,k,value)=>{await field(i,k).fill(String(value));await field(i,k).press('Tab');};
 const snapshot=()=>p.evaluate(()=>cutEditor.api('/api/roughcut/project?id='+cutEditor.snapshot().id));
 const check=async()=>{await p.locator('#column-check').click();await p.waitForFunction(()=>!document.querySelector('#column-check').disabled);return p.locator('#column-status').textContent();};
 try{
  await p.goto(process.argv[2]);await p.locator('#boot-overlay').waitFor({state:'hidden'});
  await p.locator('#nav-tools').click();await p.locator('#open-roughcut').click();await p.locator('#column-open').click();
  await p.locator('#column-preset').selectOption('ifgal');await p.locator('#column-preset').selectOption('');await p.locator('#column-name').fill('顺序组合验收');
  await p.locator('#column-visual-mode').selectOption('sequence');
  assert(await p.locator('#column-background').isDisabled());
  for(let i=0;i<2;i++){await p.locator('#column-sequence-image').selectOption(inputs.ids.sequenceVideo);await p.locator('#column-add-sequence').click();}
  await fill(0,'sourceStart',1);await fill(0,'duration',8);await fill(1,'sourceStart',12);await fill(1,'duration',12);
  //Reordering retains the independent source range attached to each item.
  await p.locator('[data-seq-up="1"]').click();assert.equal(await field(0,'sourceStart').inputValue(),'12');
  await p.locator('[data-seq-down="0"]').click();assert.equal(await field(0,'sourceStart').inputValue(),'1');
  await p.locator('#column-voice').selectOption(inputs.ids.voice);
  assert((await check()).includes('还差'));
  assert(await p.locator('#column-dialog').isVisible());
  await p.locator('#column-sequence-image').selectOption(inputs.ids.alternateImage);await p.locator('#column-add-sequence').click();
  await field(2,'timing').selectOption('remainder');assert(await field(2,'sourceStart').isDisabled());
  assert((await check()).includes('1.867 秒'));
  await p.locator('#column-sequence-panel').scrollIntoViewIfNeeded();await p.screenshot({path:path.join(root,'sequence-configuration.png')});
  await p.locator('#column-save').click();await p.waitForFunction(()=>document.querySelector('#column-status').textContent.includes('已保存常用配置'));
  const id=await p.locator('#column-preset').inputValue(),file=path.join(root,'RoughCut','column-presets',id+'.json'),before=fs.readFileSync(file,'utf8');
  for(const [i,voice] of [inputs.ids.voice,inputs.ids.longVoice].entries()){
   await p.locator('#column-voice').selectOption(voice);await p.locator('#column-episode-name').fill('顺序组合_第'+(i+1)+'期');
   assert((await check()).includes('安排可生成'));
   await p.locator('#column-build').click();await p.locator('#column-dialog').waitFor({state:'hidden'});
   const project=await snapshot();projects.push(project);
   assert.equal(project.scenes.length,3);assert.deepEqual(project.scenes.slice(0,2).map(s=>s.videoStart),[1,12]);
   assert.equal(project.scenes[2].durationUs,project.durationUs-20_000_000);
   await p.locator('#cut-export').click();await p.waitForFunction(()=>!document.querySelector('#cut-export').disabled&&document.querySelector('#cut-status').textContent.startsWith('已生成 '));
   projects[i]=await snapshot();
   await p.waitForFunction(()=>document.querySelector('#cut-preview video')?.readyState>=2);await p.screenshot({path:path.join(root,'sequence-episode-'+i+'.png')});
   if(i===0){await p.locator('#column-open').click();await p.locator('#column-preset').selectOption(id);}
  }
  assert.equal(fs.readFileSync(file,'utf8'),before);
  const first=await p.evaluate(async id=>cutEditor.api('/api/roughcut/project?id='+id),projects[0].id);
  delete first.updated;const old=structuredClone(projects[0]);delete old.updated;assert.deepEqual(first,old);
  const drafts=fs.readdirSync(path.join(root,'generated-drafts')).map(dir=>{
   const d=JSON.parse(fs.readFileSync(path.join(root,'generated-drafts',dir,'draft_content.json'),'utf8'));
   const bg=d.tracks.find(t=>t.name==='背景');assert.equal(bg.segments.length,3);
   assert.deepEqual(bg.segments.slice(0,2).map(s=>s.source_timerange.start),[1_000_000,12_000_000]);
   assert.equal(bg.segments.reduce((n,s)=>n+s.target_timerange.duration,0),d.duration);
   assert(bg.segments.every(s=>s.volume===0));assert(d.tracks.find(t=>t.name==='BGM 1').segments.every(s=>s.volume===1));
   return {directory:dir,durationUs:d.duration,fillUs:d.duration-20_000_000};
  });
  assert.equal(drafts.length,2);assert.deepEqual(errors,[]);
  fs.writeFileSync(path.join(root,'sequence-report.json'),JSON.stringify({passed:true,projects,drafts,errors},null,2));
  console.log('Ordered visuals, preview, source ranges, two-episode reuse and draft export passed.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
