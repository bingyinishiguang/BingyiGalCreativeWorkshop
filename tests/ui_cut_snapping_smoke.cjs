const assert=require('node:assert/strict'),fs=require('fs'),path=require('path'),e2e=require('./ui_e2e_helper.cjs');
(async()=>{const browser=await e2e.chromium.launch({executablePath:e2e.requireBrowser(),headless:true}),out=process.argv[3];fs.mkdirSync(out,{recursive:true});
try{
  const wav=Buffer.alloc(44+4*16000*2);wav.write('RIFF');wav.writeUInt32LE(wav.length-8,4);wav.write('WAVEfmt ',8);wav.writeUInt32LE(16,16);wav.writeUInt16LE(1,20);wav.writeUInt16LE(1,22);wav.writeUInt32LE(16000,24);wav.writeUInt32LE(32000,28);wav.writeUInt16LE(2,32);wav.writeUInt16LE(16,34);wav.write('data',36);wav.writeUInt32LE(wav.length-44,40);const wavPath=path.resolve(out,'snapping-fixture.wav');fs.writeFileSync(wavPath,wav);
  const p=await browser.newPage({viewport:{width:1366,height:768}}),errors=[];p.on('pageerror',err=>errors.push(err.message));
  await p.goto(process.argv[2]);await p.locator('#boot-overlay').waitFor({state:'hidden'});await p.locator('#nav-tools').click();await p.locator('#open-roughcut').click();await p.locator('#cut-assets button').first().waitFor({state:'visible'});
  await p.evaluate(async()=>{const bg=(await cutEditor.api('/api/backgrounds')).items[0],subtitleStyle={x:0,y:-.8,size:8,color:'#ffffff',borderColor:'#000000',borderWidth:40,showCharacter:false};cutEditor.applyTimeline({name:'吸附验收',fps:30,width:1920,height:1080,scenes:[{background:bg.id,duration:4,actors:[]},{background:bg.id,duration:6,actors:[]}],textClips:[{id:'first',text:'移动文字',character:'角色',start:1,duration:1,track:0,subtitleStyle},{id:'second',text:'目标文字',character:'角色',start:6,duration:1,track:0,subtitleStyle}],audioClips:[]});cutV2.locate(8);});
  await p.locator('[data-text-index="0"]').waitFor({state:'visible'});await p.waitForTimeout(350);
  const get=()=>p.evaluate(()=>cutEditor.snapshot());
  let capturedGuide=false;
  async function drag(selector,dx,{alt=false,trim=false,cancel=false}={}){
    const loc=p.locator(selector).first(),box=await loc.boundingBox();assert(box);
    const x=trim?(selector.includes('"left"')?box.x+2:box.x+box.width-3):box.x+Math.min(15,box.width/2),y=box.y+box.height/2;
    if(alt)await p.keyboard.down('Alt');await p.mouse.move(x,y);await p.mouse.down();await p.mouse.move(x+dx,y,{steps:4});
    const guide=await p.locator('#editor-snap-guide').evaluate(n=>!n.hidden);
    if(guide&&!capturedGuide){capturedGuide=true;await p.screenshot({path:path.join(out,'snapping-active-guide.png')});}
    if(cancel)await p.evaluate(()=>{const node=document.querySelector('[data-text-index="0"]');node.dispatchEvent(new PointerEvent('pointercancel',{bubbles:true,pointerId:1}));});
    await p.mouse.up();if(alt)await p.keyboard.up('Alt');return guide;
  }
  // Move the end to another clip's start. A single undo reverses the whole drag.
  assert(await drag('[data-text-index="0"]',3.88*35));assert.equal((await get()).textClips[0].start,5);
  await p.evaluate(()=>{document.querySelector('#roughcut-page').inert=true;document.activeElement.blur();});await p.keyboard.press('Control+z');assert.equal((await get()).textClips[0].start,5);await p.evaluate(()=>document.querySelector('#roughcut-page').inert=false);
  await p.evaluate(()=>{const dialog=document.createElement('dialog');dialog.id='snapping-test-dialog';document.body.append(dialog);dialog.showModal();});await p.keyboard.press('Control+z');assert.equal((await get()).textClips[0].start,5);await p.evaluate(()=>document.querySelector('#snapping-test-dialog').remove());
  await p.evaluate(()=>{const div=document.createElement('div');div.id='snapping-editable';div.contentEditable='true';div.textContent='可编辑文本';document.body.append(div);div.focus();});await p.keyboard.press('Control+z');assert.equal((await get()).textClips[0].start,5);await p.evaluate(()=>document.querySelector('#snapping-editable').remove());
  await p.locator('#editor-undo').click();assert.equal((await get()).textClips[0].start,1);
  assert.equal(await drag('[data-text-index="0"]',3.88*35,{alt:true}),false);assert(Math.abs((await get()).textClips[0].start-4.866666666666666)<.001);
  await p.locator('#editor-undo').click();await p.locator('#editor-snap').uncheck();
  assert.equal(await drag('[data-text-index="0"]',3.88*35),false);assert(Math.abs((await get()).textClips[0].start-4.866666666666666)<.001);
  await p.locator('#editor-undo').click();await p.locator('#editor-snap').check();
  assert(await drag('[data-text-index="0"] [data-trim]',3.88*35,{trim:true}));assert.equal((await get()).textClips[0].duration,5);
  await p.locator('#editor-undo').click();
  assert(await drag('[data-scene-index="0"] [data-trim]',1.88*35,{trim:true}));assert.equal((await get()).scenes[0].duration,6);
  await p.locator('#editor-undo').click();
  // Moving near its own original edge must not pull it back.
  assert.equal(await drag('[data-text-index="0"]',.12*35),false);assert(Math.abs((await get()).textClips[0].start-1.1333333333333333)<.001);
  await p.locator('#editor-undo').click();await drag('[data-text-index="0"]',3.88*35,{cancel:true});assert.equal((await get()).textClips[0].start,1);
  const row=p.locator('[data-text-index="0"]').locator('..').locator('..');await row.locator('[data-track-lock]').click();assert(await p.locator('[data-text-index="0"]').isDisabled());
  await row.locator('[data-track-lock]').click();
  await p.evaluate(async wavPath=>{const response=await cutEditor.api('/api/audio/import',{paths:[wavPath]});await cutV2.loadAudio();const item=response.results[0].item;cutV2.addClip(item);cutV2.updateClip(0,{start:1,sourceStart:.2,duration:1.5});cutV2.locate(8);},wavPath);
  assert(await drag('[data-audio-index="0"]',3.4*35));assert.equal((await get()).audioClips[0].start,4.5);
  await p.locator('#editor-undo').click();assert.equal((await get()).audioClips[0].start,1);
  await p.evaluate(()=>cutV2.locate(4.5));assert(await drag('[data-audio-index="0"] [data-trim="right"]',1.88*35,{trim:true}));assert.equal((await get()).audioClips[0].duration,3.5);
  await p.locator('#editor-undo').click();await p.evaluate(()=>cutV2.locate(1.5));assert(await drag('[data-audio-index="0"] [data-trim="left"]',.38*35,{trim:true}));assert.equal((await get()).audioClips[0].start,1.5);assert(Math.abs((await get()).audioClips[0].sourceStart-.7)<.001);
  await p.locator('#editor-undo').click();await p.evaluate(()=>cutV2.locate(6));assert.equal(await drag('[data-audio-index="0"] [data-trim="right"]',3.38*35,{trim:true}),false);assert((await get()).audioClips[0].sourceStart+(await get()).audioClips[0].duration<=4.001);
  await p.screenshot({path:path.join(out,'snapping-1366.png')});assert.deepEqual(errors,[]);
  console.log('Cut snapping browser: text/audio move and trims, scene trim, source bounds, Alt/toggle, own edges, lock/cancel, busy/modal/editable keyboard guards and single undo passed');
}finally{await browser.close();}})().catch(err=>{console.error(err);process.exitCode=1;});
