const fs=require('fs');
const path=require('path');
const {chromium,requireBrowser}=require('./ui_e2e_helper.cjs');
const assert=require('assert/strict');
(async()=>{
 const url=process.argv[2],out=path.resolve(process.argv[3]||'output/story-ui-validation');
 const browser=await chromium.launch({executablePath:requireBrowser(),headless:true});
 const page=await browser.newPage({viewport:{width:1600,height:1000}});const errors=[];page.on('pageerror',e=>errors.push(e.stack||e.message));
 try{
 await page.goto(url);await page.locator('#nav-tools').click();await page.locator('#open-gal-story').click();
 await page.locator('#gs-demo').click();await page.waitForFunction(()=>document.querySelectorAll('#gs-list .gs-clip').length===13);
 await page.waitForFunction(()=>!document.querySelector('#gs-frame').hidden&&document.querySelector('#gs-frame').naturalWidth>0);
 await page.locator('#gs-list .gs-clip').nth(1).click();
 await page.waitForTimeout(350);await page.locator('#gal-story-page').evaluate(e=>e.scrollTop=0);
 await page.screenshot({path:path.join(out,'story-demo.png'),fullPage:true});
 const original=await page.locator('#gs-text').inputValue();
 await page.locator('#gs-text').fill('这是一句修改过的台词。');await page.locator('#gs-text').press('Tab');
 await page.locator('#gs-undo').click();assert.equal(await page.locator('#gs-text').inputValue(),original);
 await page.locator('#gs-redo').click();assert.equal(await page.locator('#gs-text').inputValue(),'这是一句修改过的台词。');
 await page.locator('#gs-settings-tab').click();await page.locator('#gs-character-name').fill('冰翼验收');await page.locator('#gs-character-name').press('Tab');
 await page.locator('#gs-save').click();await page.waitForFunction(()=>document.querySelector('#gs-status').textContent==='项目已保存。');
 await page.reload();await page.locator('#nav-tools').click();await page.locator('#open-gal-story').click();await page.waitForFunction(()=>document.querySelectorAll('#gs-list .gs-clip').length===13);
 await page.locator('#gs-list .gs-clip').nth(1).click();assert.equal(await page.locator('#gs-text').inputValue(),'这是一句修改过的台词。');
 await page.route('**/api/gal-story/chat',async route=>{const payload=route.request().postDataJSON();assert.equal(payload.operation,'layout');const before=payload.project.clips[1],after={...before,text:'明天见，记得带上新的故事。'};await route.fulfill({json:{message:'这句可以更自然一点。',changes:[{id:before.id,before,after}]}});});
 await page.getByRole('button',{name:'对白排版',exact:true}).click();await page.locator('#gs-chat-send').click();await page.waitForFunction(()=>!document.querySelector('#gs-proposal').hidden);
 assert.equal(await page.locator('#gs-text').inputValue(),'这是一句修改过的台词。');await page.locator('#gs-apply').click();assert.equal(await page.locator('#gs-text').inputValue(),'明天见，记得带上新的故事。');await page.locator('#gs-undo').click();
 await page.locator('#gs-import').click();await page.locator('#gs-import-text').fill('冰翼：短剧验收。\n旁白：夜色温柔。');await page.locator('#gs-parse').click();await page.waitForFunction(()=>document.querySelectorAll('#gs-list .gs-clip').length===2);
 await page.locator('#gs-duration').fill('0.6');await page.locator('#gs-duration').press('Tab');await page.locator('#gs-list .gs-clip').nth(1).click();await page.locator('#gs-duration').fill('0.6');await page.locator('#gs-duration').press('Tab');
 await page.locator('#gs-mp4').click();await page.waitForFunction(()=>!document.querySelector('#gs-result').hidden,{},{timeout:90000});
 await page.waitForFunction(()=>Number.isFinite(document.querySelector('#gs-video').duration)&&document.querySelector('#gs-video').duration>0);
 const video=await page.locator('#gs-video').evaluate(v=>({src:v.src,duration:v.duration}));assert(video.src.includes('/api/gal-story/video'));assert(Math.abs(video.duration-1.2)<.1);
 await page.screenshot({path:path.join(out,'story-desktop.png'),fullPage:true});
 await page.setViewportSize({width:1100,height:850});await page.screenshot({path:path.join(out,'story-compact.png'),fullPage:true});
 await page.locator('#gs-model-settings').click();await page.waitForFunction(()=>document.querySelector('#assistant-settings').open);await page.locator('#assistant-settings-close').click();
 assert.equal(errors.length,0,errors.join('\n'));
 console.log(JSON.stringify({checks:['toolbox entry','13-clip demo','actual backend preview','manual editing','undo/redo','role editing','save/reload','AI preview/apply/undo','script parsing','actual MP4 export'],pageErrors:errors,video},null,2));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
