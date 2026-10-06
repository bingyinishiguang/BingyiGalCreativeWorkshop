/*Run against tools/production_preview.py with an isolated --data-root.*/
const assert=require('node:assert/strict'),fs=require('fs'),path=require('path');
const e2e=require('./ui_e2e_helper.cjs');
(async()=>{
  const url=process.argv[2],out=process.argv[3];
  if(!url||!out)throw Error('Usage: node tests/ui_composition_smoke.cjs URL OUTPUT_DIRECTORY');
  fs.mkdirSync(out,{recursive:true});
  const browser=await e2e.chromium.launch({executablePath:e2e.requireBrowser(),headless:true});
  try{
    const page=await browser.newPage({viewport:{width:1920,height:1080}}),errors=[];
    page.on('pageerror',error=>errors.push(error.message));page.on('dialog',d=>d.accept());
    await page.goto(url);await page.locator('#boot-overlay').waitFor({state:'hidden'});
    await page.locator('#nav-tools').click();await page.locator('#open-roughcut').click();
    await page.locator('#cut-assets [data-add-asset]').first().click();
    await page.locator('#cut-sprite-tab').click();
    await page.locator('#cut-assets .production-tile').filter({hasText:'测试人物'}).first().locator('[data-add-asset]').click();
    await page.locator('#cut-scale').waitFor();
    const edit=async(id,value)=>{await page.locator('#'+id).fill(String(value));await page.locator('#'+id).press('Tab');};
    await edit('cut-scale',180);await edit('cut-position-x',120);await edit('cut-position-y',-360);await edit('cut-rotation',8);
    const before=await page.evaluate(()=>window.cutEditor.snapshot().scenes[0].actors[0]);
    await page.locator('#cut-assets [data-replace-asset]').nth(1).click();
    const after=await page.evaluate(()=>window.cutEditor.snapshot().scenes[0].actors[0]);
    assert.notEqual(after.id,before.id);assert.deepEqual(after.transform,before.transform);
    await page.locator('#cut-scale-slider').fill('195');await page.locator('#cut-scale-slider').dispatchEvent('change');
    assert.equal(await page.locator('#cut-scale').inputValue(),'195');
    await page.locator('#cut-uniform').uncheck();await edit('cut-scale-y',120);
    let sizes=[];
    for(const size of ['1920x1080','1080x1920','1080x1440','1440x1080','1080x1080']){
      await page.locator('#studio-project-settings').click();await page.locator('#cut-canvas').selectOption(size);await page.locator('#studio-project-close').click();
      await page.waitForFunction(()=>{const im=document.querySelector('.preview-actor');return im?.complete&&im.naturalWidth>0;});
      const measure=await page.evaluate(()=>{
        const p=document.querySelector('#cut-preview').getBoundingClientRect(),im=document.querySelector('.preview-actor').getBoundingClientRect();
        return {w:p.width,h:p.height,centreX:(im.left+im.right)/2-p.left,centreY:(im.top+im.bottom)/2-p.top};
      });
      const [w,h]=size.split('x').map(Number);
      assert.ok(Math.abs(measure.w/measure.h-w/h)<.01);
      assert.ok(Math.abs(measure.centreX/measure.w-(.5+120/w))<.002);
      assert.ok(Math.abs(measure.centreY/measure.h-(.5+360/h))<.002);sizes.push(size);
    }
    await page.locator('#studio-project-settings').click();await edit('cut-width',1234);await edit('cut-height',876);await page.locator('#studio-project-close').click();
    assert.equal(await page.locator('#cut-canvas').inputValue(),'1234x876');
    await page.locator('#cut-visual-target').selectOption('background');
    await edit('cut-position-x',-80);await edit('cut-rotation',-5);
    await page.locator('#cut-visual-target').selectOption('0');
    const snapshot=await page.evaluate(()=>window.cutEditor.snapshot());
    await page.locator('#cut-save').click();await page.waitForFunction(()=>document.querySelector('#cut-status').textContent.includes('已保存'));
    const id=await page.evaluate(()=>window.cutEditor.snapshot().id);
    await page.reload();await page.locator('#boot-overlay').waitFor({state:'hidden'});
    await page.locator('#nav-tools').click();await page.locator('#open-roughcut').click();
    await page.locator('#studio-project-settings').click();await page.locator('#cut-projects').selectOption(id);await page.locator('#studio-project-close').click();
    await page.waitForFunction(()=>document.querySelector('#cut-status').textContent.includes('已打开'));
    const reopened=await page.evaluate(()=>window.cutEditor.snapshot());
    assert.equal(reopened.width,1234);assert.equal(reopened.height,876);
    assert.deepEqual(reopened.scenes[0].actors[0].transform,snapshot.scenes[0].actors[0].transform);
    assert.deepEqual(reopened.scenes[0].backgroundTransform,snapshot.scenes[0].backgroundTransform);
    await page.locator('#cut-visual-target').selectOption('0');
    await page.locator('#cut-export').click();await page.waitForFunction(()=>document.querySelector('#cut-status').textContent.includes('已生成'));
    const status=await page.locator('#cut-status').textContent();
    await page.screenshot({path:path.join(out,'composition-1920.png')});
    await page.setViewportSize({width:1366,height:768});await page.screenshot({path:path.join(out,'composition-1366.png')});
    assert.equal(errors.length,0,errors.join('\n'));
    const report={sizes,custom:'1234x876',replacementPreserved:true,reopened:true,exportStatus:status,pageErrors:errors};
    fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
