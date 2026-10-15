const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium,requireBrowser}=require('./ui_e2e_helper.cjs');
(async()=>{
 const out=path.resolve(process.argv[3]);fs.mkdirSync(out,{recursive:true});
 const browser=await chromium.launch({executablePath:requireBrowser(),headless:true}),results=[];
 async function test(name,action){
  const page=await browser.newPage({viewport:{width:1366,height:900}}),errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  try{
   await page.goto(process.argv[2]);await page.locator('#boot-overlay').waitFor({state:'hidden'});
   await page.locator('#nav-tools').click();await page.locator('#open-roughcut').click();
   await page.locator('#studio-project-settings').click();await action(page);assert.deepEqual(errors,[]);
   results.push({name,passed:true});
  }catch(error){results.push({name,passed:false,error:error.message});await page.screenshot({path:path.join(out,name+'.png'),fullPage:true});}
  finally{await page.close();}
 }
 await test('material-picker-failure',async page=>{
  await page.route('**/api/settings/choose-folder',route=>route.fulfill({status:503,json:{error:'Folder picker unavailable'}}));
  await page.locator('#cut-choose-material-directory').click();
  await page.waitForFunction(()=>document.querySelector('#cut-status').textContent.includes('Folder picker unavailable'),null,{timeout:3000});
  assert(await page.locator('#cut-choose-material-directory').isEnabled());
 });
 await test('cancel-new-keeps-empty-project-name',async page=>{
  await page.locator('#cut-name').fill('Named empty project');await page.locator('#cut-name').press('Tab');
  page.on('dialog',dialog=>dialog.dismiss());await page.locator('#cut-new').click();
  assert.equal(await page.locator('#cut-name').inputValue(),'Named empty project');
  assert(await page.evaluate(()=>cutEditor.isDirty()));
 });
 async function pendingProject(page){
  const value=await page.evaluate(()=>structuredClone(cutEditor.snapshot()));
  const project={...value,id:'a'.repeat(32),name:'Delayed project',scenes:[],audioClips:[],textClips:[]};
  await page.locator('#cut-projects').evaluate((select,project)=>select.add(new Option(project.name,project.id)),project);
  let entered,release;
  const started=new Promise(resolve=>{entered=resolve;}),waiting=new Promise(resolve=>{release=resolve;});
  await page.route('**/api/roughcut/project?*',async route=>{entered();await waiting;await route.fulfill({json:project});});
  const response=page.waitForResponse(response=>response.url().includes('/api/roughcut/project?'));
  await page.locator('#cut-projects').selectOption(project.id);await started;
  return {release,response};
 }
 await test('new-project-cancels-pending-load',async page=>{
  const {release,response}=await pendingProject(page);
  await page.locator('#cut-new').click();
  release();await response;await page.waitForTimeout(200);
  assert.equal(await page.locator('#cut-name').inputValue(),'新草稿项目');
  assert(!await page.evaluate(()=>cutEditor.snapshot().id));
 });
 await test('editing-cancels-pending-load',async page=>{
  const {release,response}=await pendingProject(page);
  await page.locator('#cut-name').fill('Keep my current changes');await page.locator('#cut-name').press('Tab');
  release();await response;await page.waitForTimeout(200);
  assert.equal(await page.locator('#cut-name').inputValue(),'Keep my current changes');
  assert(await page.evaluate(()=>cutEditor.isDirty()));
 });
 await browser.close();fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(results,null,2));console.log(JSON.stringify(results));
 if(results.some(result=>!result.passed))process.exitCode=1;
})().catch(error=>{console.error(error);process.exitCode=1;});
