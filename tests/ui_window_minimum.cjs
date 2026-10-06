const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const e2e = require('./ui_e2e_helper.cjs');
(async()=>{
 const out=process.argv[3];fs.mkdirSync(out,{recursive:true});
 const browser=await e2e.chromium.launch({executablePath:e2e.requireBrowser(),headless:true});
 const results=[];
 try {
 for(const [workW,workH,dpi] of [[1920,1040,1],[1920,1040,1.25],[1366,728,1],[1920,1040,1.5],[1280,680,2]]){
  let limits;
  const context=await browser.newContext({viewport:{width:Math.floor(workW/dpi),height:Math.floor(workH/dpi)},deviceScaleFactor:dpi});
  await context.exposeBinding('nativeFit',async(_,width,height)=>{
   const border=Math.ceil(16*dpi);
   const fit=Math.min(1,(workW-24-border)/(width*dpi),(workH-24-border)/(height*dpi));
   limits={fit,width:Math.ceil(width*dpi*fit)+border,height:Math.ceil(height*dpi*fit)+border};return limits;
  });
  await context.addInitScript(()=>{window.pywebview={api:{fit_workspace:(w,h)=>window.nativeFit(w,h),get_state:async()=>({desktop:true,maximized:false}),log_frontend:()=>{},set_caption_color:()=>{}}};});
  const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(process.argv[2]+'?shell=desktop');await page.locator('#boot-overlay').waitFor({state:'hidden'});
  await page.waitForFunction(()=>document.body.style.getPropertyValue('--desktop-fit'));
  await page.evaluate(()=>window.configurationWorkspace.open());
  await page.waitForTimeout(300);
  await page.setViewportSize({width:Math.floor((limits.width-Math.ceil(16*dpi))/dpi),height:Math.floor((limits.height-Math.ceil(16*dpi))/dpi)});
  await page.waitForTimeout(400);
  const report=await page.evaluate(()=>{
   const rect=selector=>{const r=document.querySelector(selector).getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,right:r.right,bottom:r.bottom};};
   return {viewport:[innerWidth,innerHeight],fit:Number(document.body.style.getPropertyValue('--desktop-fit')),header:rect('.app-header'),settings:rect('#settings-button'),controls:rect('.window-controls'),preview:rect('#cfg-preview'),body:rect('.cfg-body'),timeline:rect('.cfg-timeline'),save:rect('#cfg-save'),build:rect('#cfg-build'),lanes:[...document.querySelectorAll('.cfg-lane')].map(e=>e.getBoundingClientRect().height),overflow:document.documentElement.scrollWidth>innerWidth+1,iconLoaded:document.querySelector('.compact-product-icon').naturalWidth>0};
  });
  assert(report.iconLoaded);assert(!report.overflow,JSON.stringify(report));
  assert(report.preview.height>=120*report.fit,'preview collapsed');
  assert(report.timeline.height>=280*report.fit,'timeline collapsed');
  assert(report.save.right<=report.viewport[0]+1 && report.build.right<=report.viewport[0]+1,'toolbar clipped');
  assert(report.settings.right<=report.controls.x,'settings overlaps controls');
  assert(report.body.bottom<=report.timeline.y+1,'panels overlap timeline');
  assert(report.lanes.length===4 && report.lanes.every(h=>h>=50*report.fit),'track rows inaccessible');
  await page.locator('#cfg-properties').click();await page.locator('#cfg-episode').fill('最小窗口验收');
  assert.deepEqual(errors,[]);await page.screenshot({path:path.join(out,`minimum-${workW}-${dpi}.png`)});
  results.push({workW,workH,dpi,limits,...report});await context.close();
 }
 fs.writeFileSync(path.join(out,'minimum-report.json'),JSON.stringify(results,null,2));console.log('Desktop minimum layout passed for '+results.length+' monitor/DPI combinations');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
