//Browser-side layout/state regression. Native Windows restore remains a separate check.
const assert=require('node:assert/strict');
const e2e=require('./ui_e2e_helper.cjs');
(async()=>{
  const url=process.argv[2];if(!url)throw Error('Provide an existing workshop URL');
  const browser=await e2e.chromium.launch({executablePath:e2e.requireBrowser(),headless:true});
  try{
    const page=await browser.newPage({viewport:{width:1366,height:768}});
    await page.goto(url);await page.waitForFunction(()=>window.cutEditor);
    await page.evaluate(()=>switchPage('roughcut'));
    await page.waitForSelector('#editor-preview-holder');
    const original=await page.evaluate(()=>JSON.stringify(window.cutEditor.snapshot()));
    const saved=await page.evaluate(()=>localStorage.getItem('bingyi-cut-layout-v1'));
    //A hidden renderer must not overwrite sizes or layout preferences.
    const previous=await page.evaluate(()=>{
      const root=document.getElementById('roughcut-page');
      Object.defineProperty(document,'hidden',{configurable:true,get:()=>true});
      const height=root.style.height;window.dispatchEvent(new Event('resize'));return height;
    });
    await page.setViewportSize({width:1024,height:680});
    assert.equal(await page.evaluate(()=>document.getElementById('roughcut-page').style.height),previous);
    await page.evaluate(()=>{delete document.hidden;document.dispatchEvent(new Event('visibilitychange'));window.dispatchEvent(new Event('focus'));});
    await page.waitForTimeout(400);
    for(const [width,height] of [[1024,680],[1366,768],[1920,1080]]){
      await page.setViewportSize({width,height});await page.waitForTimeout(150);
      const layout=await page.evaluate(()=>{
        const root=document.getElementById('roughcut-page'),dock=root.querySelector('.editor-dock');
        const top=root.querySelector('.editor-top'),timeline=root.querySelector('.editor-timeline-panel');
        return {rootHeight:parseFloat(root.style.height),remaining:innerHeight-root.getBoundingClientRect().top,
          available:dock.clientHeight-root.querySelector('.editor-divider.horizontal').offsetHeight,
          used:parseFloat(top.style.height)+parseFloat(timeline.style.height)};
      });
      assert.ok(Math.abs(layout.rootHeight-layout.remaining)<2,JSON.stringify(layout));
      assert.ok(Math.abs(layout.used-layout.available)<2,JSON.stringify(layout));
    }
    assert.equal(await page.evaluate(()=>JSON.stringify(window.cutEditor.snapshot())),original);
    assert.equal(await page.evaluate(()=>localStorage.getItem('bingyi-cut-layout-v1')),saved);
    console.log('browser cut layout recovery passed; native Windows minimize/restore not covered');
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
