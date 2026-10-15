const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const e2e = require('./ui_e2e_helper.cjs');

(async () => {
  const out = path.resolve(process.argv[3]);
  fs.mkdirSync(out, {recursive:true});
  const browser = await e2e.chromium.launch({executablePath:e2e.requireBrowser(),headless:true});
  const page = await browser.newPage({viewport:{width:1366,height:768}});
  const errors = [], checks = [];
  page.on('pageerror', e => errors.push(e.message));
  try {
    await page.goto(process.argv[2]);
    await page.locator('#boot-overlay').waitFor({state:'hidden'});
    await page.locator('#nav-tools').click();
    assert.equal(await page.locator('.tools-section-title').count(),2);
    assert.equal(await page.locator('#tools-page .tool-card').count(),4);
    await page.screenshot({path:path.join(out,'toolbox.png')});
    checks.push('Toolbox groups match creation and existing work');

    await page.locator('#open-gal-story').click();
    await page.locator('#gs-import').waitFor({state:'visible'});
    await page.waitForFunction(() => !document.querySelector('#gs-import').disabled);
    await page.locator('#gs-step-import').click();
    await page.locator('#gs-import-text').fill('冰翼：新故事开始了。\n旁白：窗外是一片蓝色。');
    await page.locator('#gs-parse').click();
    await page.waitForFunction(() => document.querySelectorAll('#gs-list .gs-clip').length===2);
    await page.locator('#gs-step-settings').click();
    assert(await page.locator('#gs-character-name').isVisible());
    const sections = page.locator('#gs-settings-pane details[data-settings-section]');
    assert.deepEqual(await sections.evaluateAll(ds=>ds.filter(d=>d.open).map(d=>d.dataset.settingsSection)),['characters']);
    await page.locator('[data-settings-section="audio"] > summary').click();
    await page.locator('#gs-bgm-volume').fill('0.25');
    await page.locator('#gs-bgm-volume').press('Tab');
    assert.equal(await page.locator('[data-settings-section="audio"]').evaluate(d=>d.open),true);
    assert.equal(await page.locator('#gs-bgm-volume').inputValue(),'0.25');
    await page.locator('[data-settings-section="output"] > summary').click();
    assert(await page.locator('#gs-material-directory').isVisible());
    await page.locator('[data-settings-section="output"] > summary').click();
    checks.push('Guided import, editable settings, disclosure state retained after editing');

    for (const [width,height] of [[1920,1080],[1366,768],[1100,768],[700,740],[360,740]]) {
      await page.setViewportSize({width,height});
      const overflow = await page.evaluate(() => ({document:document.documentElement.scrollWidth>innerWidth+1, page:document.querySelector('#gal-story-page').scrollWidth>document.querySelector('#gal-story-page').clientWidth+1}));
      assert(!overflow.document && !overflow.page,`Story overflow at ${width}: ${JSON.stringify(overflow)}`);
      await page.screenshot({path:path.join(out,`story-${width}.png`)});
    }
    checks.push('Story workspace fits five viewport sizes');

    await page.setViewportSize({width:1366,height:768});
    await page.locator('#settings-button').click();
    await page.locator('#open-localtts').click();
    await page.waitForFunction(() => document.querySelector('#tts-component-info').textContent.length>0);
    assert.equal(await page.locator('#tts-advanced').evaluate(d=>d.open),false);
    assert.equal(await page.locator('#tts-preset').evaluate(d=>d.open),false);
    await page.locator('#tts-advanced > summary').click();
    await page.locator('#tts-sampleSteps').selectOption('16');
    assert.equal(await page.locator('#tts-sampleSteps').inputValue(),'16');
    await page.locator('#tts-advanced > summary').click();
    assert(await page.locator('#tts-generate').isVisible());
    await page.screenshot({path:path.join(out,'voice.png')});
    checks.push('Voice generation keeps basic workflow visible, optional parameters accessible');

    await page.locator('#nav-library').click();
    await page.locator('#library-grid .library-tile').first().waitFor();
    await page.locator('#library-grid .library-tile').first().click();
    assert(await page.locator('#library-detail-preview').isVisible());
    await page.locator('#nav-backgrounds').click();
    await page.locator('#bg-grid .production-tile').first().waitFor();
    assert(await page.locator('#bg-import').isVisible());
    await page.locator('#nav-audio').click();
    assert(await page.locator('#audio-library-root').isVisible());
    checks.push('Sprite, background and audio entries remain accessible');

    await page.locator('#nav-tools').click();
    await page.locator('#open-existing-draft').click();
    assert.equal(await page.locator('#existing-install').inputValue(),'');
    assert.equal(await page.locator('#video-assets-root').inputValue(),'');
    assert(await page.locator('#existing-load').isVisible());
    checks.push('Existing draft entry has clear steps and no developer machine defaults');
    assert.deepEqual(errors,[]);
    const report = {checks,errors};
    fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(report,null,2));
    console.log(JSON.stringify(report));
  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exitCode=1;});
