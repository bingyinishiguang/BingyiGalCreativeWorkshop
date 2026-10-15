const fs=require('fs'),path=require('path'),assert=require('assert/strict');
const {chromium,requireBrowser}=require('./ui_e2e_helper.cjs');
(async()=>{
 const url=process.argv[2],out=path.resolve(process.argv[3]);fs.mkdirSync(out,{recursive:true});
 const media=path.join(out,'本期素材');fs.mkdirSync(media,{recursive:true});
 const browser=await chromium.launch({executablePath:requireBrowser(),headless:true});
 const page=await browser.newPage({viewport:{width:1600,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 try{
  await page.goto(url);await page.locator('#nav-tools').click();await page.locator('#open-gal-story').click();await page.locator('#gs-demo').click();
  await page.waitForFunction(()=>document.querySelectorAll('#gs-list .gs-clip').length===13);
  await page.locator('#gs-settings-tab').click();await page.locator('[data-settings-section="output"] > summary').click();await page.locator('#gs-material-directory').fill(media);await page.locator('#gs-material-directory').press('Tab');
  assert.equal(await page.locator('#gs-export').textContent(),'生成剪映草稿');
  await page.locator('#gs-export').click();await page.waitForFunction(()=>!document.querySelector('#gs-result').hidden,{},{timeout:90000});
  assert.equal(await page.locator('#gs-video').isVisible(),false);
  assert((await page.locator('#gs-result-title').textContent()).includes('剪映草稿'));
  const draftPath=await page.locator('#gs-open-folder').getAttribute('data-path');
  const content=JSON.parse(fs.readFileSync(path.join(draftPath,'draft_content.json'),'utf8'));
  assert(content.materials.texts.length>10);
  for(const v of content.materials.videos){assert(fs.existsSync(v.path));assert.equal(path.dirname(v.path),media);}
  await page.screenshot({path:path.join(out,'draft-studio.png'),fullPage:true});
  await page.reload();await page.locator('#nav-tools').click();await page.locator('#open-gal-story').click();await page.locator('#gs-settings-tab').click();
  await page.locator('[data-settings-section="output"] > summary').click();
  await page.waitForFunction(()=>document.querySelector('#gs-material-directory')?.value.length>0);
  assert.equal(await page.locator('#gs-material-directory').inputValue(),media);
  await page.waitForFunction(()=>!document.querySelector('#gs-result').hidden);
  await page.evaluate(()=>window.switchPage('roughcut'));
  await page.locator('#studio-project-settings').click();
  assert(await page.locator('#cut-material-directory').isVisible());
  await page.locator('#cut-material-directory').fill(media);
  await page.locator('#studio-project-close').click();
  assert.equal(errors.length,0,errors.join('\n'));
  console.log(JSON.stringify({draftPath,materialDirectory:media,editableTexts:content.materials.texts.length,errors}));
 }catch(error){await page.screenshot({path:path.join(out,'failure.png'),fullPage:true});console.error(await page.locator('#gs-status').textContent(),await page.locator('#gs-job-message').textContent(),errors);throw error;}finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
