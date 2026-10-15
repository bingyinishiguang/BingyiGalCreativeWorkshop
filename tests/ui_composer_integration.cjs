const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium,requireBrowser}=require('./ui_e2e_helper.cjs');
(async()=>{
 const out=path.resolve(process.argv[3]);fs.mkdirSync(out,{recursive:true});const browser=await chromium.launch({executablePath:requireBrowser(),headless:true}),page=await browser.newPage({viewport:{width:1366,height:900}}),errors=[];page.on('pageerror',error=>errors.push(error.message));
 try{
  await page.goto(process.argv[2]);await page.locator('#boot-overlay').waitFor({state:'hidden'});await page.waitForFunction(()=>document.querySelector('#preview').naturalWidth>0);
  const original=await page.locator('#face').inputValue();await page.locator('#face-next').click();assert.notEqual(await page.locator('#face').inputValue(),original);await page.locator('#face-prev').click();assert.equal(await page.locator('#face').inputValue(),original);
  const settings=await page.request.post(new URL('/api/settings',process.argv[2]).href,{data:{singleMode:'browser',singlePath:'',batchPath:'',dragPath:''}});assert(settings.ok());
  await page.locator('#settings-button').click();await page.locator('#nav-workbench').click();
  const downloaded=page.waitForEvent('download');await page.locator('#download').click();const file=await downloaded;await file.saveAs(path.join(out,'single.png'));assert(fs.statSync(path.join(out,'single.png')).size>100);
  await page.locator('#save-library').click();await page.waitForFunction(()=>document.querySelector('#save-library-status').textContent.includes('保存')||document.querySelector('#save-library-status').textContent.includes('入库'));
  await page.locator('#open-custom-batch').click();await page.locator('#batch-inspector-image').waitFor({state:'visible'});await page.locator('#batch-select-all').click();await page.locator('#batch-add').click();assert.equal(await page.locator('.batch-queue-row').count(),2);
  await page.locator('#batch-start').click();await page.waitForFunction(()=>document.querySelector('#batch-result').textContent.startsWith('完成：'),{},{timeout:60000});assert((await page.locator('#batch-result').textContent()).includes('成功 2 张，失败 0 张'));assert.equal(await page.locator('.batch-queue-row').count(),0);
  await page.locator('#close-custom-batch').click();await page.locator('#open-custom-batch').click();await page.locator('#batch-select-all').click();await page.locator('#batch-add').click();await page.locator('#close-custom-batch').click();await page.locator('#batch-library-quick').click();await page.locator('#batch-library-save').click();await page.waitForFunction(()=>document.querySelector('#batch-library-status').textContent.includes('完成'),{},{timeout:60000});
  await page.locator('#close-custom-batch').click();await page.locator('#nav-library').click();await page.waitForFunction(()=>document.querySelector('#library-count').textContent.includes('张立绘'));assert((await page.locator('.library-tile').count())>=2);assert.deepEqual(errors,[]);await page.screenshot({path:path.join(out,'composed-library.png')});console.log(JSON.stringify({passed:true,checks:['real PNG layer preview','face switching','single PNG export','single library save','batch PNG export','batch library save'],errors}));
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
