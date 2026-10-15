/* Real imported WAV, voice-driven preview, BGM controls and actual audio export. */
const fs=require('fs'),path=require('path'),assert=require('assert/strict');
const {chromium,requireBrowser}=require('./ui_e2e_helper.cjs');
(async()=>{
 const url=process.argv[2],out=path.resolve(process.argv[3]);
 const sample=path.join(out,'voice-fixture.wav'),rate=48000,count=rate*1.8;
 const wav=Buffer.alloc(44+count*2);wav.write('RIFF');wav.writeUInt32LE(wav.length-8,4);wav.write('WAVEfmt ',8);wav.writeUInt32LE(16,16);wav.writeUInt16LE(1,20);wav.writeUInt16LE(1,22);wav.writeUInt32LE(rate,24);wav.writeUInt32LE(rate*2,28);wav.writeUInt16LE(2,32);wav.writeUInt16LE(16,34);wav.write('data',36);wav.writeUInt32LE(count*2,40);for(let i=0;i<count;i++)wav.writeInt16LE(Math.round(Math.sin(i/rate*440*2*Math.PI)*1000),44+i*2);fs.writeFileSync(sample,wav);
 const browser=await chromium.launch({executablePath:requireBrowser(),headless:true});const page=await browser.newPage({viewport:{width:1500,height:1000}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 try{
 await page.goto(url);await page.locator('#nav-tools').click();await page.locator('#open-gal-story').click();await page.locator('#gs-new').click();await page.locator('#gs-import').click();await page.locator('#gs-import-text').fill('冰翼：声音播放结束以后，才进入下一句。\n旁白：现在是第二句。');await page.locator('#gs-parse').click();
 await page.route('**/api/audio/pick',route=>route.fulfill({json:{paths:[sample]}}));
 await page.locator('#gs-audio-import').click();await page.waitForFunction(()=>document.querySelector('#gs-status').textContent==='音频已导入并绑定。');
 await page.locator('#gs-duration').fill('0.2');await page.locator('#gs-duration').press('Tab');await page.waitForTimeout(400);
 await page.locator('#gs-play').click();await page.waitForFunction(()=>document.querySelector('#gs-speech').currentTime>.4);
 assert.equal(await page.locator('#gs-list .active').getAttribute('data-index'),'0');
 await page.waitForFunction(()=>document.querySelector('#gs-list .active').dataset.index==='1');
 const ended=await page.locator('#gs-speech').evaluate(a=>({ended:a.ended,currentTime:a.currentTime,duration:a.duration}));assert(ended.currentTime>=1.75,JSON.stringify(ended));
 await page.locator('#gs-play').click();await page.locator('#gs-settings-tab').click();await page.locator('[data-settings-section=audio] > summary').click();await page.locator('#gs-import-bgm').click();await page.waitForFunction(()=>document.querySelector('#gs-bgm').value!=='');
 await page.locator('#gs-bgm-volume').fill('0.1');await page.locator('#gs-bgm-volume').press('Tab');
 await page.locator('#gs-mp4').click();await page.waitForFunction(()=>!document.querySelector('#gs-result').hidden,{},{timeout:90000});await page.waitForFunction(()=>Number.isFinite(document.querySelector('#gs-video').duration));
 const duration=await page.locator('#gs-video').evaluate(v=>v.duration);assert(duration>1.8);
 // Editing a focused textarea must survive reload without relying on blur.
 await page.locator('#gs-text').fill('还没有离开输入框的修改。');await page.reload();await page.locator('#nav-tools').click();await page.locator('#open-gal-story').click();await page.waitForFunction(()=>document.querySelectorAll('#gs-list .gs-clip').length===2);await page.locator('#gs-list .gs-clip').nth(1).click();assert.equal(await page.locator('#gs-text').inputValue(),'还没有离开输入框的修改。');
 // Server save also restores the project after origin-local draft storage is cleared.
 const fresh=await browser.newPage();await fresh.goto(url);await fresh.locator('#nav-tools').click();await fresh.locator('#open-gal-story').click();await fresh.waitForFunction(()=>document.querySelectorAll('#gs-list .gs-clip').length===2);
 await fresh.waitForFunction(()=>!document.querySelector('#gs-result').hidden);await fresh.close();
 await page.locator('#gs-video').evaluate(v=>{v.muted=true;v.loop=true;return v.play();});
 await page.locator('#nav-tools').click();assert(await page.locator('#gs-video').evaluate(v=>v.paused),'output playback must stop when leaving the workspace');
 await page.locator('#open-gal-story').click();
 await page.locator('#gs-video').evaluate(v=>v.play());await page.locator('#gs-new').click();
 await page.waitForFunction(()=>document.querySelector('#gs-name').value==='新剧情'&&!document.querySelector('#gal-story-page').inert);
 assert(await page.locator('#gs-video').evaluate(v=>v.paused),'replacing a project must stop its previous output');
 assert.equal(errors.length,0,errors.join('\n'));console.log(JSON.stringify({checks:['real WAV import and binding','voice drives preview timing','audio reaches end before next sentence','BGM import and controls','actual audio MP4 export','focused edit survives reload','server project recovery','completed video recovery','hidden output stops playing'],duration,pageErrors:errors}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
