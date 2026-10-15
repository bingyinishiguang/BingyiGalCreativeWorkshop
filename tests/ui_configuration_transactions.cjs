const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {chromium,requireBrowser}=require('./ui_e2e_helper.cjs');

(async()=>{
  const out=path.resolve(process.argv[3]);fs.mkdirSync(out,{recursive:true});
  const browser=await chromium.launch({executablePath:requireBrowser(),headless:true}),results=[];
  async function test(name,action){
    const page=await browser.newPage({viewport:{width:1366,height:900}}),errors=[];
    page.on('pageerror',error=>errors.push(error.stack||error.message));
    try{
      const items=['A','B','C'].map((name,i)=>({id:String(i+1).repeat(32),name,duration:3,kind:'dialogue',cues:[],missing:false}));
      await page.route(/\/api\/audio(?:\?|$)/,route=>route.fulfill({json:{items,total:3}}));
      await page.route('**/api/roughcut/columns',route=>route.fulfill({json:{items:[]}}));
      await page.route('**/api/roughcut/column-save',route=>route.fulfill({json:{...route.request().postDataJSON(),revision:1}}));
      await page.goto(process.argv[2]);await page.locator('#boot-overlay').waitFor({state:'hidden'});
      await page.locator('#nav-tools').click();await page.locator('#open-roughcut').click();await page.locator('#column-open').click();
      await page.locator('#configuration-page').waitFor({state:'visible'});
      await action(page,items);
      assert.deepEqual(errors,[]);results.push({name,passed:true});
    }catch(error){results.push({name,passed:false,error:error.message,pageErrors:errors});await page.screenshot({path:path.join(out,name+'.png'),fullPage:true});}
    finally{await page.close();}
  }
  const snapshot=page=>page.evaluate(()=>configurationWorkspace.snapshot());
  await test('pending-configuration-keeps-navigation-stable',async page=>{
    let entered,release;
    const ready=new Promise(resolve=>{entered=resolve;}),waiting=new Promise(resolve=>{release=resolve;});
    await page.route('**/api/roughcut/column-save',async route=>{entered();await waiting;await route.fulfill({json:{...route.request().postDataJSON(),revision:1}});});
    const response=page.waitForResponse(response=>response.url().endsWith('/api/roughcut/column-save'));response.catch(()=>{});
    await page.locator('#cfg-save').click();await ready;
    await page.locator('#settings-button').click({timeout:250}).catch(()=>{});
    const stayed=await page.locator('#configuration-page').isVisible();release();await response;
    await page.waitForFunction(()=>!document.querySelector('#configuration-page').classList.contains('busy'));
    assert(stayed,'navigation during an unfinished configuration transaction can replace the wrong project');
    await page.locator('#settings-button').click();assert(await page.locator('#settings-page').isVisible());
  });
  await test('configuration-isolates-editor-controls',async page=>{
    assert(await page.locator('#assistant-ball').isHidden(),'the hidden project assistant must not edit another workspace');
    await page.locator('#cfg-back').click();assert(await page.locator('#assistant-ball').isVisible());
    await page.locator('#studio-text').click();await page.locator('#studio-add-default-text').click();
    await page.locator('#dialogue-play').click();assert(await page.evaluate(()=>cutV2.isPlaying()));
    const original=await page.evaluate(()=>JSON.stringify(cutEditor.snapshot()));
    await page.locator('#column-open').click();await page.locator('#configuration-page').waitFor({state:'visible'});
    assert.equal(await page.evaluate(()=>cutV2.isPlaying()),false);
    assert(await page.locator('#assistant-ball').isHidden());
    assert.equal(await page.evaluate(()=>JSON.stringify(cutEditor.snapshot())),original);
  });
  async function addVoices(page,items){
    await page.locator('[data-cfg-purpose="voice"]').click();
    for(const item of items)await page.locator(`[data-cfg-asset="${item.id}"] [data-cfg-add]`).click();
  }
  await test('voice-drop-before-target',async(page,items)=>{
    await addVoices(page,items);
    const drag=await page.evaluateHandle(()=>new DataTransfer());
    await page.locator('[data-type="voice"][data-id="0"]').dispatchEvent('dragstart',{dataTransfer:drag});
    await page.locator('[data-type="voice"][data-id="2"]').dispatchEvent('drop',{dataTransfer:drag});
    assert.deepEqual((await snapshot(page)).episode.voices.map(voice=>voice.audio),[items[1].id,items[0].id,items[2].id]);
    await page.locator('#cfg-undo').click();
    assert.deepEqual((await snapshot(page)).episode.voices.map(voice=>voice.audio),items.map(item=>item.id));
    await page.locator('#cfg-redo').click();
    assert.deepEqual((await snapshot(page)).episode.voices.map(voice=>voice.audio),[items[1].id,items[0].id,items[2].id]);
  });
  await test('new-keeps-unsaved-episode-on-cancel',async(page,items)=>{
    await addVoices(page,items.slice(0,1));
    await page.locator('#cfg-save').click();await page.waitForFunction(()=>!document.querySelector('#configuration-page').classList.contains('busy'));
    let confirmations=0;page.on('dialog',async dialog=>{confirmations++;await dialog.dismiss();});
    await page.locator('#cfg-new').click();
    assert.equal(confirmations,1);
    assert.equal((await snapshot(page)).episode.voices.length,1);
  });
  await test('closed-workspace-still-protects-episode',async(page,items)=>{
    await addVoices(page,items.slice(0,1));
    await page.locator('#cfg-save').click();await page.waitForFunction(()=>!document.querySelector('#configuration-page').classList.contains('busy'));
    await page.locator('#cfg-back').click();
    assert.equal(await page.evaluate(()=>Object.values(window.workshopActivity||{}).some(check=>check())),true);
    const protectedOnUnload=await page.evaluate(()=>{const event=new Event('beforeunload',{cancelable:true});window.dispatchEvent(event);return event.defaultPrevented;});
    assert(protectedOnUnload);
  });
  await browser.close();fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(results,null,2));console.log(JSON.stringify(results));
  if(results.some(result=>!result.passed))process.exitCode=1;
})().catch(error=>{console.error(error);process.exitCode=1;});
