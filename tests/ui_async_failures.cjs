const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium,requireBrowser}=require('./ui_e2e_helper.cjs');
(async()=>{
 const out=path.resolve(process.argv[3]);fs.mkdirSync(out,{recursive:true});
 const browser=await chromium.launch({executablePath:requireBrowser(),headless:true}),results=[];
 async function test(name,action){
  const page=await browser.newPage({viewport:{width:1366,height:900}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  try{await action(page);assert.deepEqual(errors,[]);results.push({name,passed:true});}
  catch(error){results.push({name,passed:false,error:error.message});await page.screenshot({path:path.join(out,name+'.png'),fullPage:true});}
  finally{await page.close();}
 }
 const open=async page=>{await page.goto(process.argv[2]);await page.locator('#boot-overlay').waitFor({state:'hidden'});};
 await test('audio-record-warning-keeps-library-usable',async page=>{
  const item={id:'1'.repeat(32),name:'Usable audio',kind:'dialogue',text:'Line',duration:1,cues:[],tags:[],work:'',character:'',missing:false};
  await page.route(/\/api\/audio(?:\?|$)/,r=>r.fulfill({json:{items:[item],total:1,warnings:[{record:'broken.json',message:'Audio metadata unavailable'}]}}));
  await open(page);await page.locator('#nav-audio').click();await page.locator('.audio-row').click();
  assert.equal(await page.locator('#audio-name').inputValue(),item.name);
  assert.match(await page.locator('#audio-count').textContent(),/1 条音频资料暂不可用/);
  assert(await page.locator('#audio-import').isEnabled());assert(await page.locator('#audio-save').isEnabled());
 });
 await test('audio-subtitle-import-keeps-selection',async page=>{
  const items=['A','B'].map((name,i)=>({id:String(i+1).repeat(32),name,kind:'dialogue',text:name,duration:1,cues:[],tags:[],work:'',character:'',missing:false}));
  await page.route(/\/api\/audio(?:\?|$)/,r=>r.fulfill({json:{items,total:2}}));
  await page.route('**/api/audio/srt',async r=>{await new Promise(resolve=>setTimeout(resolve,250));await r.fulfill({json:{cues:[{start:0,end:1,text:'Subtitle'}]}});});
  await page.route('**/api/audio/update',r=>r.fulfill({json:{...items[0],...r.request().postDataJSON()}}));
  await open(page);await page.locator('#nav-audio').click();await page.locator('.audio-row').first().click();await page.locator('#audio-attach-srt').click();
  await page.locator('.audio-row').nth(1).click();await page.waitForTimeout(600);
  assert.equal(await page.locator('#audio-name').inputValue(),'B');
 });
 await test('audio-subtitle-import-keeps-new-edits',async page=>{
  const item={id:'1'.repeat(32),name:'Original',kind:'dialogue',text:'Line',duration:1,cues:[],tags:[],work:'',character:'',missing:false};
  await page.route(/\/api\/audio(?:\?|$)/,r=>r.fulfill({json:{items:[item],total:1}}));
  await page.route('**/api/audio/srt',async r=>{await new Promise(resolve=>setTimeout(resolve,250));await r.fulfill({json:{cues:[{start:0,end:1,text:'Subtitle'}]}});});
  await page.route('**/api/audio/update',r=>r.fulfill({json:{...item,...r.request().postDataJSON()}}));
  await open(page);await page.locator('#nav-audio').click();await page.locator('.audio-row').click();await page.locator('#audio-attach-srt').click();
  await page.locator('#audio-name').fill('Keep my edits');await page.waitForTimeout(600);
  assert.equal(await page.locator('#audio-name').inputValue(),'Keep my edits');assert(await page.locator('#audio-save').isEnabled());
 });
 await test('audio-trash-keeps-other-detail',async page=>{
  const items=['A','B'].map((name,i)=>({id:String(i+1).repeat(32),name,kind:'dialogue',text:name,duration:1,cues:[],tags:[],work:'',character:'',missing:false}));
  await page.route(/\/api\/audio(?:\?|$)/,r=>r.fulfill({json:{items,total:2}}));
  await page.route('**/api/audio/update',async r=>{await new Promise(resolve=>setTimeout(resolve,250));await r.fulfill({json:{...items[0],...r.request().postDataJSON()}});});
  await open(page);await page.locator('#nav-audio').click();await page.locator('.audio-row').first().click();await page.locator('#audio-trash').click();
  await page.locator('.audio-row').nth(1).click();await page.waitForTimeout(600);
  assert.equal(await page.locator('#audio-name').count(),1);assert.equal(await page.locator('#audio-name').inputValue(),'B');
 });
 await test('background-trash-keeps-other-detail',async page=>{
  const items=['A','B'].map((name,i)=>({id:String(i+1).repeat(32),name,kind:'image',width:1,height:1,tags:[],missing:false,thumbnail:true}));
  await page.route(/\/api\/backgrounds(?:\?|$)/,r=>r.fulfill({json:{items,total:2}}));
  await page.route('**/api/backgrounds/trash',async r=>{await new Promise(resolve=>setTimeout(resolve,250));await r.fulfill({json:{ok:true}});});
  await open(page);await page.locator('#nav-backgrounds').click();await page.locator('#bg-grid .asset-open').first().click();await page.locator('#bg-trash').click();
  await page.locator('#bg-grid .asset-open').nth(1).click();await page.waitForTimeout(600);
  assert.equal(await page.locator('#bg-edit-name').count(),1);assert.equal(await page.locator('#bg-edit-name').inputValue(),'B');
 });
 await test('audio-save-selection',async page=>{
  const items=['A','B'].map((name,i)=>({id:String(i+1).repeat(32),name,kind:'dialogue',text:name+'台词',character:name,duration:1,cues:[],tags:[],work:'',missing:false}));
  await page.route(/\/api\/audio(?:\?|$)/,r=>r.fulfill({json:{items,total:items.length}}));
  let saving=false;await page.route('**/api/audio/update',async r=>{saving=true;await new Promise(resolve=>setTimeout(resolve,450));await r.fulfill({json:{...items[0],...r.request().postDataJSON()}});});
  await open(page);await page.locator('#nav-audio').click();await page.locator('.audio-row').filter({hasText:'A台词'}).count();
  await page.locator('.audio-row').filter({hasText:'A'}).first().click();await page.locator('#audio-name').fill('A更新');await page.locator('#audio-save').click();
  await page.waitForFunction(()=>document.querySelector('#audio-detail')!==null);while(!saving)await new Promise(resolve=>setTimeout(resolve,10));
  await page.locator('.audio-row').filter({hasText:'B'}).click();await page.waitForTimeout(750);
  assert.equal(await page.locator('#audio-name').inputValue(),'B','late save must not switch back to A');
 });
 await test('voice-history-refresh',async page=>{
  let count=1;await page.route('**/api/localtts/history*',r=>r.fulfill({json:{items:Array.from({length:count},(_,i)=>({id:String(i+1).repeat(32),name:'版本'+i,text:'台词',duration:1,preset:{name:'音色'},created:new Date().toISOString()}))}}));
  await open(page);await page.locator('#settings-button').click();await page.locator('#open-localtts').click();await page.locator('.tts-take').waitFor();
  await page.locator('#nav-tools').click();count=2;await page.locator('#settings-button').click();await page.locator('#open-localtts').click();await page.waitForTimeout(500);
  assert.equal(await page.locator('.tts-take').count(),2,'history must refresh when returning');
 });
 await test('audio-new-edits-survive-save',async page=>{
  const item={id:'1'.repeat(32),name:'原名称',kind:'dialogue',text:'台词',character:'角色',duration:1,cues:[],tags:[],work:'',missing:false};
  await page.route(/\/api\/audio(?:\?|$)/,r=>r.fulfill({json:{items:[item],total:1}}));
  const writes=[];await page.route('**/api/audio/update',async r=>{const values=r.request().postDataJSON();writes.push(values);await new Promise(resolve=>setTimeout(resolve,400));await r.fulfill({json:{...item,...values}});});
  await open(page);await page.locator('#nav-audio').click();await page.locator('.audio-row').click();await page.locator('#audio-name').fill('第一次修改');await page.locator('#audio-save').click();
  await page.locator('#audio-name').fill('第二次修改');await page.waitForTimeout(650);
  assert.equal(await page.locator('#audio-name').inputValue(),'第二次修改');assert(await page.locator('#audio-save').isEnabled());
  await page.locator('#audio-save').click();await page.waitForTimeout(650);assert.equal(writes.at(-1).name,'第二次修改');
 });
 await test('sprite-save-selection',async page=>{
  const items=['A','B'].map((name,i)=>({id:String(i+1).repeat(32),displayName:name,note:'',favorite:false,tags:[],game:'测试作品',character:'测试角色',body:'standing',face:'smile',width:1,height:1,savedAt:new Date().toISOString(),missing:false}));
  await page.route(/\/api\/library(?:\?|$)/,r=>r.fulfill({json:{items,total:2,tags:[],games:[],characters:[]}}));
  await page.route('**/api/library/update',async r=>{await new Promise(resolve=>setTimeout(resolve,450));await r.fulfill({json:{...items[0],...r.request().postDataJSON()}});});
  await open(page);await page.locator('#nav-library').click();await page.locator('.library-tile').first().click();await page.locator('#library-edit-name').fill('A更新');await page.locator('#library-save-edit').click();await page.locator('.library-tile').nth(1).click();await page.waitForTimeout(750);
  assert.equal(await page.locator('#library-edit-name').inputValue(),'B','sprite save must preserve current selection');
 });
 await test('background-save-selection',async page=>{
  const items=['A','B'].map((name,i)=>({id:String(i+1).repeat(32),name,kind:'image',tags:[],favorite:false,width:1,height:1,missing:false,thumbnail:true}));
  await page.route(/\/api\/backgrounds(?:\?|$)/,r=>r.fulfill({json:{items,total:2}}));
  await page.route('**/api/backgrounds/update',async r=>{await new Promise(resolve=>setTimeout(resolve,450));await r.fulfill({json:{...items[0],...r.request().postDataJSON()}});});
  await open(page);await page.locator('#nav-backgrounds').click();await page.locator('#bg-grid .asset-open').first().click();await page.locator('#bg-edit-name').fill('A更新');await page.locator('#bg-edit-save').click();await page.locator('#bg-grid .asset-open').nth(1).click();await page.waitForTimeout(750);
  assert.equal(await page.locator('#bg-edit-name').inputValue(),'B','background save must preserve current selection');
 });
 await test('audio-search-out-of-order',async page=>{
  const items=['A','B'].map((name,i)=>({id:String(i+1).repeat(32),name,kind:'bgm',text:'',character:'',duration:1,cues:[],tags:[],work:'',missing:false}));
  let delayed=false;await page.route(/\/api\/audio(?:\?|$)/,async r=>{const url=new URL(r.request().url());if(!url.search&&!delayed){delayed=true;await new Promise(resolve=>setTimeout(resolve,800));}const search=url.searchParams.get('search');const shown=items.filter(i=>!search||i.name.includes(search));await r.fulfill({json:{items:shown,total:shown.length}});});
  await open(page);await page.locator('#nav-audio').click();while(!delayed)await new Promise(resolve=>setTimeout(resolve,10));
  await page.locator('#audio-search').fill('B');await page.waitForTimeout(1100);assert.equal(await page.locator('.audio-row').count(),1);assert((await page.locator('.audio-row').textContent()).startsWith('B'));
 });
 await test('broken-asset-reports-error',async page=>{
  await page.route('**/api/backgrounds/media?*',r=>r.fulfill({status:404,body:''}));await open(page);await page.locator('#nav-tools').click();await page.locator('#open-roughcut').click();await page.locator('#cut-assets .asset-open').first().click();
  await page.waitForFunction(()=>document.querySelector('#cut-status').textContent.includes('无法预览'));
 });
 await test('story-save-failure-preserves-project',async page=>{
  await open(page);await page.locator('#nav-tools').click();await page.locator('#open-gal-story').click();await page.waitForFunction(()=>!document.querySelector('#gs-new').disabled);
  await page.locator('#gs-demo').click();await page.waitForFunction(()=>document.querySelectorAll('#gs-list .gs-clip').length===13);
  await page.waitForFunction(()=>!document.querySelector('#gal-story-page').inert);
  await page.locator('#gs-name').fill('不能丢失的修改');await page.locator('#gs-name').press('Tab');
  assert.equal(await page.evaluate(()=>JSON.parse(localStorage.getItem('bingyi-gal-story-draft')).name),'不能丢失的修改');
  await page.route('**/api/gal-story/save',r=>r.fulfill({status:503,json:{error:'测试保存失败'}}));
  await page.locator('#gs-new').click();await page.waitForTimeout(600);
  assert.equal(await page.locator('#gs-name').inputValue(),'不能丢失的修改','failed save must stop project replacement');
  assert((await page.locator('#gs-status').textContent()).includes('保存失败'));
 });
 await test('invalid-story-cache-recovers',async page=>{
  await open(page);await page.evaluate(()=>localStorage.setItem('bingyi-gal-story-draft',JSON.stringify({version:1,id:'invalid-cache',characters:[]})));
  await page.locator('#nav-tools').click();await page.locator('#open-gal-story').click();await page.waitForTimeout(700);
  assert(await page.locator('#gs-new').isEnabled(),'invalid cache must not disable the module permanently');
  assert((await page.evaluate(()=>localStorage.getItem('bingyi-gal-story-recovery'))).includes('invalid-cache'));
 });
 async function story(page){await open(page);await page.locator('#nav-tools').click();await page.locator('#open-gal-story').click();await page.waitForFunction(()=>!document.querySelector('#gs-demo').disabled);await page.locator('#gs-demo').click();await page.waitForFunction(()=>document.querySelectorAll('#gs-list .gs-clip').length===13&&!document.querySelector('#gal-story-page').inert);}
 await test('lost-task-unlocks-controls',async page=>{
  await story(page);await page.route('**/api/gal-story/draft',r=>r.fulfill({json:{id:'lost-job'}}));
  await page.route('**/api/gal-story/job?*',r=>r.fulfill({status:400,json:{error:'任务不存在'}}));
  await page.locator('#gs-export').click();await page.waitForTimeout(700);
  assert(await page.locator('#gs-export').isEnabled(),'lost job must release export controls');
  assert(await page.locator('#gs-job').isHidden());
 });
 await test('completed-task-refresh-failure',async page=>{
  await story(page);await page.route('**/api/gal-story/draft',r=>r.fulfill({json:{id:'done-job'}}));
  await page.route('**/api/gal-story/job?*',r=>r.fulfill({json:{id:'done-job',state:'complete',kind:'draft',message:'已生成',progress:1,path:'测试草稿',metadata:{width:1920,height:1080,duration:3}}}));
  await page.route(/\/api\/audio(?:\?|$)/,r=>r.fulfill({status:503,json:{error:'列表暂时不可用'}}));
  await page.locator('#gs-export').click();await page.waitForTimeout(700);
  assert(await page.locator('#gs-export').isEnabled(),'list refresh error must not leave controls locked');
  assert(await page.locator('#gs-result').isVisible(),'completed output must remain available');
 });
 await test('old-project-output-stays-separate',async page=>{
  await story(page);let complete=false;await page.route('**/api/gal-story/draft',r=>r.fulfill({json:{id:'old-project-job'}}));
  await page.route('**/api/gal-story/job?*',r=>r.fulfill({json:complete?{state:'complete',kind:'draft',message:'已生成',progress:1,path:'旧项目草稿',metadata:{width:1920,height:1080,duration:3}}:{state:'running',progress:.1,message:'生成中'}}));
  await page.locator('#gs-export').click();await page.locator('#gs-job').waitFor({state:'visible'});await page.locator('#gs-new').click();await page.waitForFunction(()=>document.querySelector('#gs-name').value==='新剧情'&&!document.querySelector('#gal-story-page').inert);complete=true;await page.waitForTimeout(1200);
  assert(await page.locator('#gs-result').isHidden(),'old output must not be shown as the new project result');
 });
 await test('legacy-entry-initializes-panels',async page=>{
  let profiles=[];await page.route('**/api/script/presets',r=>r.fulfill({json:{items:profiles}}));
  await open(page);await page.locator('#nav-tools').click();await page.locator('#open-roughcut').click();
  await page.locator('#cut-assets [data-add-asset]').first().click();
  await page.waitForTimeout(300);
  profiles=[{id:'fixture-profile',name:'测试声音'}];
  await page.evaluate(()=>{cutScript.captureBase();cutEditor.render();});
  await page.locator('#draft-open-legacy').click();await page.waitForTimeout(600);
  assert((await page.locator('#script-rule-preset option').count())>1,'compatibility entry must initialize voice presets');
 });
 await browser.close();fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(results,null,2));console.log(JSON.stringify(results));
 if(results.some(r=>!r.passed))process.exitCode=1;
})().catch(error=>{console.error(error);process.exitCode=1;});
