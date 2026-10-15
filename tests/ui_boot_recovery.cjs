const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium,requireBrowser}=require('./ui_e2e_helper.cjs');
(async()=>{
 const out=path.resolve(process.argv[3]);fs.mkdirSync(out,{recursive:true});
 const browser=await chromium.launch({executablePath:requireBrowser(),headless:true}),results=[];
 async function test(name,action){
  const page=await browser.newPage({viewport:{width:1366,height:900}}),errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  try{await action(page);assert.deepEqual(errors,[]);results.push({name,passed:true});}
  catch(error){results.push({name,passed:false,error:error.message});await page.screenshot({path:path.join(out,name+'.png'),fullPage:true});}
  finally{await page.close();}
 }
 await test('catalog-failure-can-retry',async page=>{
  await require('./ui_composer_fixture.cjs').mockComposer(page);
  let requests=0;const loaded=new Set();
  page.on('request',request=>{if(/\/api\/(brand|settings)$/.test(request.url()))loaded.add(new URL(request.url()).pathname);});
  await page.route('**/api/catalog',route=>++requests===1?route.fulfill({status:503,json:{error:'Temporary catalog failure'}}):route.fallback());
  await page.goto(process.argv[2]);await page.locator('#boot-overlay').waitFor({state:'hidden'});
  assert(loaded.has('/api/settings'),'settings must remain available after a catalog failure');
  assert(loaded.has('/api/brand'),'brand and license metadata must load independently');
  assert(await page.locator('#boot-retry').isVisible());await page.locator('#boot-retry').click();
  await page.waitForFunction(()=>document.querySelector('#preview').naturalWidth>0);
  assert(await page.locator('#boot-retry').isHidden());assert(await page.locator('#download').isEnabled());
 });
 await test('license-works-without-brand-metadata',async page=>{
  await page.route('**/api/brand',route=>route.fulfill({status:503,json:{error:'Brand unavailable'}}));
  let filename='';await page.route('**/api/settings/open-folder',route=>{filename=route.request().postDataJSON().name;return route.fulfill({json:{ok:true,path:'LICENSE.txt'}});});
  await page.goto(process.argv[2]);await page.locator('#boot-overlay').waitFor({state:'hidden'});
  await page.locator('#settings-button').click();await page.locator('[data-settings-open="panel-about"]').click();
  await page.locator('#open-license-file').click();await page.waitForTimeout(100);
  assert.equal(filename,'LICENSE.txt');
 });
 await browser.close();fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(results,null,2));console.log(JSON.stringify(results));
 if(results.some(result=>!result.passed))process.exitCode=1;
})().catch(error=>{console.error(error);process.exitCode=1;});
