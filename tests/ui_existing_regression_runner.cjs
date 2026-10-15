/* Run the established browser suites in independent contexts and fixtures. */
const fs=require('fs'),path=require('path'),assert=require('assert/strict');
const {chromium,requireBrowser}=require('./ui_e2e_helper.cjs');
const {expect}=require(path.join(path.dirname(require.resolve(process.env.BINGYI_PLAYWRIGHT||'playwright')),'test'));
const AsyncFunction=Object.getPrototypeOf(async function(){}).constructor;
const {createDraftFixture}=require('./ui_draft_fixture.cjs');
const root=path.resolve(process.env.BINGYI_RECOVERY_ROOT||'output/recovery-workbench');
(async()=>{
 const browser=await chromium.launch({executablePath:requireBrowser(),headless:true});const reports=[];
 try{
  for(const suite of ['ui_existing_style_smoke.js','ui_existing_autosave_smoke.js','ui_existing_workbench_smoke.js','ui_existing_model_settings_smoke.js']){
   const context=await browser.newContext({viewport:{width:1520,height:950}});const page=await context.newPage();
   try{
    const fixture=createDraftFixture(path.join(root,'regression-'+suite+'-'+Date.now(),'draft_content.json'));
    await page.goto(fs.readFileSync(path.join(root,'preview-url.txt'),'utf8').trim(),{waitUntil:'domcontentloaded'});
    if(suite==='ui_existing_workbench_smoke.js')await page.route('**/api/assistant/settings',async route=>{if(route.request().method()==='GET')await route.fulfill({json:{models:[{id:'local-mock',name:'本地模拟模型'}],activeModelId:'local-mock'}});else await route.continue();});
    await page.locator('#nav-tools').click();await page.locator('#open-existing-draft').click();await page.locator('#existing-path').fill(fixture);await page.locator('#existing-load').click();await expect(page.locator('#existing-status')).toContainText('已载入');await page.locator('#existing-auto-save').uncheck();
    if(suite==='ui_existing_style_smoke.js')await page.locator('#existing-style summary').click();
    const result=await new AsyncFunction('page','expect','assert',fs.readFileSync(path.join(__dirname,suite),'utf8'))(page,expect,assert);
    reports.push({suite,...result});console.log(suite+' passed: '+result.checks.length);
   }finally{await context.close();}
  }
  fs.writeFileSync(path.join(root,'legacy-ui-verification.json'),JSON.stringify(reports,null,2));console.log(JSON.stringify(reports));
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
