/*Independent image/video previews must never add or replace timeline content.*/
const assert=require('node:assert/strict'),fs=require('fs'),path=require('path'),e2e=require('./ui_e2e_helper.cjs');
(async()=>{
 const out=process.argv[3];fs.mkdirSync(out,{recursive:true});
 const browser=await e2e.chromium.launch({executablePath:e2e.requireBrowser(),headless:true});
 const page=await browser.newPage({viewport:{width:1920,height:1080}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 try{
  await page.goto(process.argv[2]);await page.locator('#boot-overlay').waitFor({state:'hidden'});
  await page.locator('#nav-tools').click();await page.locator('#open-roughcut').click();
  const snapshot=()=>page.evaluate(()=>structuredClone(cutEditor.snapshot()));
  const initial=await snapshot();
  await page.locator('#cut-assets .production-tile').filter({hasText:'图片'}).first().locator('.asset-open').click();
  await page.waitForFunction(()=>document.querySelector('.asset-preview-media')?.naturalWidth>0);
  assert.equal(await page.locator('dialog[open]').count(),0);
  assert.equal(await page.locator('#cut-asset-preview-close').count(),0);
  assert.deepEqual(await snapshot(),initial);
  await page.screenshot({path:path.join(out,'image-preview.png')});
  await page.locator('#cut-assets .production-tile').filter({hasText:'图片'}).first().locator('[data-add-asset]').click();
  const project=await snapshot();assert.equal(project.scenes.length,1);
  await page.locator('#cut-assets .production-tile').filter({hasText:'图片'}).nth(1).locator('.asset-open').click();assert.deepEqual(await snapshot(),project);
  await page.locator('.editor-segment.background').first().click();
  assert.equal(await page.locator('#cut-preview.asset-previewing').count(),0);
  await page.waitForFunction(()=>document.querySelector('.preview-bg')?.naturalWidth>0);
  const file=path.resolve(process.argv[4]);
  const response=await page.request.post(new URL('/api/backgrounds/import',process.argv[2]).href,{data:{paths:[file]}});
  assert(response.ok(),await response.text());
  await page.locator('#cut-bg-tab').click();
  const imported=(await response.json()).results[0];assert(imported.item,JSON.stringify(imported));const card=page.locator('#cut-assets .production-tile').filter({has:page.locator('[data-add-asset="'+imported.item.id+'"]')});
  await card.locator('.asset-open').click();
  await page.waitForFunction(()=>{const v=document.querySelector('#cut-preview.asset-previewing video');return v&&!v.paused&&v.currentTime>.1;});
  assert.deepEqual(await snapshot(),project);assert.equal(await page.locator('dialog[open]').count(),0);
  await page.locator('#dialogue-stop').click();
  assert(await page.locator('.asset-preview-media').evaluate(v=>v.paused));
  assert.equal(await page.locator('#cut-preview.asset-previewing').count(),1);
  await page.locator('#dialogue-play').click();await page.waitForFunction(()=>!document.querySelector('.asset-preview-media').paused);
  await page.screenshot({path:path.join(out,'video-preview.png')});
  await page.locator('#cut-sprite-tab').click();await page.locator('#cut-assets .asset-open').first().click();
  await page.waitForFunction(()=>document.querySelector('.asset-preview-media')?.naturalWidth>0);
  assert.equal(await page.locator('#cut-preview video').count(),0);assert.deepEqual(await snapshot(),project);
  await page.screenshot({path:path.join(out,'sprite-preview.png')});
  await page.locator('.editor-segment.background').first().click();
  assert.equal(await page.locator('#cut-preview.asset-previewing').count(),0);
  assert.deepEqual(await snapshot(),project);assert.deepEqual(errors,[]);
  fs.writeFileSync(path.join(out,'report.json'),JSON.stringify({checks:['image displayed without modal or timeline mutation','timeline click restores composition','unplaced video autoplays with independent pause/play','switching to image stops video','unplaced sprite displayed','page errors absent'],pageErrors:errors},null,2));
  console.log('Image, video, sprite and timeline-preview switching passed.');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
