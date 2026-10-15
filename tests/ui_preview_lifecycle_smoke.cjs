const assert=require('node:assert/strict'),fs=require('fs'),path=require('path'),e2e=require('./ui_e2e_helper.cjs');
(async()=>{const browser=await e2e.chromium.launch({executablePath:e2e.requireBrowser(),headless:true}),out=process.argv[3];fs.mkdirSync(out,{recursive:true});
try{
  const p=await browser.newPage({viewport:{width:1366,height:768}}),errors=[];p.on('pageerror',err=>errors.push(err.message));
  // Virtual audio responses keep this regression independent of the user's library.
  const wav=Buffer.alloc(44+16000*2*8);wav.write('RIFF');wav.writeUInt32LE(wav.length-8,4);wav.write('WAVEfmt ',8);wav.writeUInt32LE(16,16);wav.writeUInt16LE(1,20);wav.writeUInt16LE(1,22);wav.writeUInt32LE(16000,24);wav.writeUInt32LE(32000,28);wav.writeUInt16LE(2,32);wav.writeUInt16LE(16,34);wav.write('data',36);wav.writeUInt32LE(wav.length-44,40);
  const items=[1,2].map(n=>({id:'preview-audit-'+n,name:'验收音频 '+n,duration:8,cues:[],kind:'dialogue',character:'角色',text:'',missing:false}));
  await p.route(/\/api\/audio(?:\?|$)/,r=>r.fulfill({json:{items,total:items.length}}));
  await p.route('**/api/audio/media?*',r=>r.fulfill({body:wav,contentType:'audio/wav'}));
  await p.route('**/api/audio/update',async r=>{const body=r.request().postDataJSON();r.fulfill({json:{...items.find(i=>i.id===body.id),...body}});});
  await p.goto(process.argv[2]);await p.locator('#boot-overlay').waitFor({state:'hidden'});await p.locator('#nav-tools').click();await p.locator('#open-roughcut').click();await p.locator('#cut-assets button').first().waitFor({state:'visible'});
  await p.evaluate(async()=>{const bg=(await cutEditor.api('/api/backgrounds')).items[0],subtitleStyle={x:0,y:-.8,size:8,color:'#ffffff',borderColor:'#000000',borderWidth:40,showCharacter:false};cutEditor.applyTimeline({name:'预览生命周期验收',width:1920,height:1080,fps:30,scenes:[{background:bg.id,duration:8,actors:[]}],textClips:[{id:'text-audit',text:'工程文字',start:0,duration:8,track:0,character:'角色',subtitleStyle}],audioClips:[{id:'audio-audit',audio:'preview-audit-1',start:0,sourceStart:0,duration:8,track:0,kind:'dialogue',volume:1,character:'角色',text:'工程字幕',subtitles:true,cues:[{start:0,end:8,text:'工程字幕'}],subtitleStyle}]});cutV2.locate(0);});
  await p.waitForTimeout(400);
  await p.evaluate(async()=>cutEditor.previewAsset((await cutEditor.api('/api/backgrounds')).items[0],'background'));
  await p.setViewportSize({width:1920,height:1080});await p.waitForTimeout(350);
  assert.equal(await p.locator('#cut-preview.asset-previewing').count(),1);assert.equal(await p.locator('#cut-preview .standalone-text,#cut-preview .dialogue-subtitle').count(),0);
  await p.screenshot({path:path.join(out,'asset-without-project-subtitles.png')});await p.keyboard.press('Escape');
  assert.equal(await p.locator('#cut-preview .standalone-text').count(),1);assert.equal(await p.locator('#cut-preview .dialogue-subtitle').count(),1);
  await p.evaluate(()=>cutEditor.previewAsset(cutV2.audioItems()[0],'audio'));await p.setViewportSize({width:1366,height:768});await p.waitForTimeout(350);assert.equal(await p.locator('#cut-preview .standalone-text,#cut-preview .dialogue-subtitle').count(),0);await p.keyboard.press('Escape');assert.equal(await p.locator('#cut-preview .standalone-text').count(),1);
  await p.evaluate(()=>switchPage('audio'));await p.locator('#audio-list button').first().click();
  const remember=()=>p.evaluate(async()=>{window.previewAuditOld=document.querySelector('#audio-detail audio');await previewAuditOld.play();});
  const paused=()=>p.evaluate(()=>previewAuditOld.paused);
  await remember();await p.locator('#audio-list button').nth(1).click();assert(await paused());assert.equal(await p.evaluate(()=>previewAuditOld.isConnected),false);
  await remember();await p.locator('#audio-save').click();await p.waitForFunction(()=>document.querySelector('#audio-status').textContent.includes('已保存'));assert(await paused());assert.equal(await p.evaluate(()=>previewAuditOld.isConnected),false);
  await remember();await p.locator('#audio-trash').click();await p.waitForFunction(()=>!document.querySelector('#audio-detail audio'));assert(await paused());
  await p.locator('#audio-list button').first().click();await remember();await p.evaluate(()=>switchPage('roughcut'));assert(await paused());
  assert.deepEqual(errors,[]);console.log('Preview lifecycle: image/audio resize stays clean, Escape restores project captions, audio switch/save/trash/leave stops old players passed');
}finally{await browser.close();}})().catch(err=>{console.error(err);process.exitCode=1;});
