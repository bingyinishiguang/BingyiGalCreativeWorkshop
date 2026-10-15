const assert=require('node:assert/strict'),fs=require('fs'),path=require('path'),e2e=require('./ui_e2e_helper.cjs');
(async()=>{const browser=await e2e.chromium.launch({executablePath:e2e.requireBrowser(),headless:true}),out=process.argv[3];fs.mkdirSync(out,{recursive:true});
try{
  const p=await browser.newPage({viewport:{width:1366,height:768}}),errors=[];p.on('pageerror',err=>errors.push(err.message));
  await p.goto(process.argv[2]);await p.locator('#boot-overlay').waitFor({state:'hidden'});await p.locator('#nav-tools').click();await p.locator('#open-roughcut').click();await p.locator('#cut-assets button').first().waitFor({state:'visible'});
  await p.evaluate(async()=>{
    const bg=(await cutEditor.api('/api/backgrounds')).items.find(i=>i.kind==='image'),audio=(await cutEditor.api('/api/audio')).items.find(i=>!i.missing);
    if(!audio)throw Error('This focused test requires an isolated synthetic audio fixture');
    const style={x:0,y:-.8,size:8,color:'#ffffff',borderColor:'#000000',borderWidth:40,showCharacter:false},duration=Math.min(4,audio.duration);
    const saved=await cutEditor.api('/api/roughcut/save',{name:'预览文字拖动验收-'+Date.now(),width:1920,height:1080,fps:30,scenes:[{background:bg.id,duration,actors:[]}],textClips:[{id:'text-drag',text:'独立文字拖动验收',start:0,duration,track:0,subtitleStyle:{...style,y:-.25}}],audioClips:[{id:'caption-drag',audio:audio.id,start:0,sourceStart:0,duration,kind:'dialogue',track:0,volume:1,text:'对白字幕拖动验收',character:'',subtitles:true,cues:[{start:0,end:duration,text:'对白字幕拖动验收'}],subtitleStyle:style}]});
    window.dragTestBaseline=saved;cutEditor.restore(saved);cutV2.locate(0);
  });
  await p.waitForTimeout(350);
  const styleOf=kind=>p.evaluate(kind=>structuredClone(cutEditor.snapshot()[kind==='text'?'textClips':'audioClips'][0].subtitleStyle),kind);
  const clean=async()=>{await p.evaluate(()=>{cutEditor.restore(dragTestBaseline);cutV2.locate(0);});assert.equal(await p.evaluate(()=>cutEditor.isDirty()),false);assert(await p.locator('#editor-undo').isDisabled());};
  const begin=async selector=>{const loc=p.locator(selector),box=await loc.boundingBox();assert(box);const x=box.x+box.width/2,y=box.y+box.height/2;await p.mouse.move(x,y);await p.mouse.down();await p.mouse.move(x+45,y-25,{steps:3});return loc;};
  for(const kind of ['text','caption']){
    const selector='#cut-preview .'+(kind==='text'?'standalone-text':'dialogue-subtitle');await clean();const original=await styleOf(kind);
    await p.locator(selector).click();assert.deepEqual(await styleOf(kind),original);assert.equal(await p.evaluate(()=>cutEditor.isDirty()),false);assert(await p.locator('#editor-undo').isDisabled());
    for(const reason of ['pointercancel','lostpointercapture']){
      await clean();const node=await begin(selector);assert.deepEqual(await styleOf(kind),original);assert.equal(await p.evaluate(()=>cutEditor.isDirty()),false);
      await node.evaluate((n,reason)=>n.dispatchEvent(new PointerEvent(reason,{pointerId:1,bubbles:true})),reason);await p.mouse.up();assert.deepEqual(await styleOf(kind),original);assert.equal(await p.evaluate(()=>cutEditor.isDirty()),false);assert(await p.locator('#editor-undo').isDisabled());
    }
    await clean();await begin(selector);await p.evaluate(()=>cutEditor.render());await p.mouse.up();assert.deepEqual(await styleOf(kind),original);assert.equal(await p.evaluate(()=>cutEditor.isDirty()),false);
    await clean();await begin(selector);assert.deepEqual(await styleOf(kind),original);await p.mouse.up();const moved=await styleOf(kind);assert.notDeepEqual(moved,original);assert.equal(await p.evaluate(()=>cutEditor.isDirty()),true);
    await p.locator('#editor-undo').click();assert.deepEqual(await styleOf(kind),original);assert(await p.locator('#editor-undo').isDisabled());await p.locator('#editor-redo').click();assert.deepEqual(await styleOf(kind),moved);
    await p.evaluate(async()=>{const saved=await cutEditor.api('/api/roughcut/save',structuredClone(cutEditor.snapshot()));const reopened=await cutEditor.api('/api/roughcut/project?id='+saved.id);cutEditor.restore(reopened);cutV2.locate(0);});assert.deepEqual(await styleOf(kind),moved);assert.equal(await p.evaluate(()=>cutEditor.isDirty()),false);
  }
  // Legacy clips may still inherit the global default. Moving an unselected
  // second group must create a local override, never move the first group.
  await p.evaluate(async()=>{const project=structuredClone(dragTestBaseline);project.name='默认样式独立拖动验收';project.audioClips[0].duration=2;const second=structuredClone(project.audioClips[0]);second.id='second-caption';second.start=2;second.cues=[{start:0,end:2,text:'继承默认样式的第二组'}];delete second.subtitleStyle;project.audioClips.push(second);const saved=await cutEditor.api('/api/roughcut/save',project);cutEditor.restore(saved);cutV2.locate(2.5);});
  const defaultStyle=await p.evaluate(()=>structuredClone(cutEditor.snapshot().subtitleStyle)),firstStyle=await p.evaluate(()=>structuredClone(cutEditor.snapshot().audioClips[0].subtitleStyle));assert.equal(await p.evaluate(()=>cutEditor.snapshot().audioClips[1].subtitleStyle),undefined);
  await begin('#cut-preview .dialogue-subtitle');assert.deepEqual(await p.evaluate(()=>cutEditor.snapshot().subtitleStyle),defaultStyle);await p.mouse.up();
  assert.deepEqual(await p.evaluate(()=>cutEditor.snapshot().subtitleStyle),defaultStyle);assert.deepEqual(await p.evaluate(()=>cutEditor.snapshot().audioClips[0].subtitleStyle),firstStyle);assert.notDeepEqual(await p.evaluate(()=>cutEditor.snapshot().audioClips[1].subtitleStyle),defaultStyle);
  await p.screenshot({path:path.join(out,'preview-drag-saved.png')});assert.deepEqual(errors,[]);
  console.log('Text and dialogue preview drag: click clean, staged move, cancel/lost capture/render interruption, single undo/redo and save/reopen passed');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
