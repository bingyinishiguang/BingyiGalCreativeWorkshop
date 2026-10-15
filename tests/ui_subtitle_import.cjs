const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium,requireBrowser}=require('./ui_e2e_helper.cjs');
(async()=>{
 const out=path.resolve(process.argv[3]);fs.mkdirSync(out,{recursive:true});
 const browser=await chromium.launch({executablePath:requireBrowser(),headless:true}),results=[];
 const cues=[{start:0,end:1,text:'Imported subtitle'}];
 async function test(name,action){
  const page=await browser.newPage({viewport:{width:1366,height:900}}),errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  try{
   await page.goto(process.argv[2]);await page.locator('#boot-overlay').waitFor({state:'hidden'});
   await page.locator('#nav-tools').click();await page.locator('#open-roughcut').click();await page.locator('#studio-text').click();
   await action(page);assert.deepEqual(errors,[]);results.push({name,passed:true});
  }catch(error){results.push({name,passed:false,error:error.message});await page.screenshot({path:path.join(out,name+'.png'),fullPage:true});}
  finally{await page.close();}
 }
 async function pending(page){
  let entered,release;
  const ready=new Promise(resolve=>{entered=resolve;}),waiting=new Promise(resolve=>{release=resolve;});
  await page.route('**/api/audio/srt',async route=>{entered();await waiting;await route.fulfill({json:{cues}});});
  const response=page.waitForResponse(response=>response.url().endsWith('/api/audio/srt'));
  response.catch(()=>{});
  await page.locator('#text-srt').click();await ready;return {release,response};
 }
 await test('empty-subtitle-does-not-change-project',async page=>{
  await page.route('**/api/audio/srt',route=>route.fulfill({json:{cues:[]}}));
  await page.locator('#text-srt').click();await page.waitForTimeout(100);
  assert.equal(await page.evaluate(()=>cutEditor.isDirty()),false);
  assert.equal(await page.evaluate(()=>cutEditor.snapshot().textClips.length),0);
 });
 await test('out-of-range-import-is-atomic',async page=>{
  await page.route('**/api/audio/srt',route=>route.fulfill({json:{cues:[...cues,{start:10800,end:10801,text:'Too late'}]}}));
  await page.locator('#text-srt').click();await page.waitForTimeout(100);
  assert.equal(await page.evaluate(()=>cutEditor.snapshot().textClips.length),0);
  assert.equal(await page.evaluate(()=>cutEditor.isDirty()),false);
 });
 await test('import-keeps-original-playhead',async page=>{
  await page.locator('#studio-add-default-text').click();await page.evaluate(()=>cutV2.locate(1));
  const {release,response}=await pending(page);await page.evaluate(()=>cutV2.locate(2));release();await response;
  await page.waitForFunction(()=>cutEditor.snapshot().textClips.length===2);
  assert.equal(await page.evaluate(()=>cutEditor.snapshot().textClips[1].start),1);
 });
 await test('new-project-rejects-stale-import',async page=>{
  const {release,response}=await pending(page);
  const locked=await page.locator('#text-srt').isDisabled();
  await page.locator('#studio-project-settings').click();await page.locator('#cut-new').click();await page.locator('#studio-project-close').click();
  release();await response;await page.waitForTimeout(150);
  assert(locked);
  assert.equal(await page.evaluate(()=>cutEditor.snapshot().textClips.length),0);
  assert.equal(await page.evaluate(()=>cutEditor.isDirty()),false);
  assert(await page.locator('#text-srt').isEnabled());
 });
 await browser.close();fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(results,null,2));console.log(JSON.stringify(results));
 if(results.some(result=>!result.passed))process.exitCode=1;
})().catch(error=>{console.error(error);process.exitCode=1;});
