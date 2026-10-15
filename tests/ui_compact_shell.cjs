const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const e2e = require('./ui_e2e_helper.cjs');
(async () => {
  const root = process.argv[3];
  fs.mkdirSync(root, {recursive:true});
  const browser = await e2e.chromium.launch({executablePath:e2e.requireBrowser(), headless:true});
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const results = [];
  try {
    await page.route('**/api/catalog', route => route.fulfill({json:{}}));
    await page.goto(process.argv[2]);
    await page.locator('#boot-overlay').waitFor({state:'hidden'});
    assert.equal(await page.title(), '冰翼Gal创作工坊');
    assert.equal(await page.locator('.app-header .brand-avatar').count(), 0);
    assert.equal(await page.locator('#panel-about .about-author img').count(), 1);
    assert.equal(await page.locator('#workspace-decoration').count(), 0);
    assert.equal(await page.locator('.empty-mascot').count(), 0);
    await page.locator('#empty-import').click();
    assert(await page.locator('#panel-packs').isVisible());
    assert.match(await page.locator('#settings-subtitle').textContent(), /ZIP/);
    await page.locator('#nav-workbench').click();
    for (const [width,height] of [[1920,1080],[1366,768],[900,600],[700,600]]) {
      await page.setViewportSize({width,height});
      assert.equal(await page.locator('.brand-copy h1').textContent(), '冰翼Gal创作工坊');
      assert.equal(await page.locator('.brand-copy h1').isVisible(), true);
      await page.locator('#nav-workbench').click();
      await page.waitForFunction(() => document.querySelector('#workbench-page').getBoundingClientRect().bottom <= innerHeight + 1);
      const geometry = await page.evaluate(() => {
        const rect = selector => {
          const b=document.querySelector(selector).getBoundingClientRect();
          return {x:b.x,y:b.y,width:b.width,height:b.height,right:b.right,bottom:b.bottom};
        };
        return {header:rect('.app-header'),workspace:rect('#workbench-page'),nav:rect('.app-nav'),settings:rect('#settings-button'),
          horizontalOverflow:document.documentElement.scrollWidth>innerWidth,
          navButtons:[...document.querySelectorAll('.nav-tab')].map(el=>({text:el.textContent,height:el.getBoundingClientRect().height})),
          preview:rect('.preview-panel')};
      });
      assert(!geometry.horizontalOverflow, `horizontal overflow at ${width}`);
      assert(geometry.header.height <= (width<=760?90:50), `header too tall at ${width}`);
      assert(geometry.settings.width>=32 && geometry.settings.height>=32);
      assert(geometry.navButtons.every(button=>button.height>=32));
      assert(geometry.workspace.bottom<=height+1, `workspace outside viewport at ${width}`);
      assert(geometry.preview.width>0 && geometry.preview.height>0);
      results.push({width,height,...geometry});
      await page.screenshot({path:path.join(root,`shell-${width}.png`)});
    }
    await page.setViewportSize({width:1366,height:768});
    await page.locator('#settings-button').click();
    assert.equal(await page.locator('[data-settings-open="panel-display"]').count(), 0);
    assert.equal(await page.locator('#settings-list small').count(), 0);
    assert.equal(errors.length, 0, errors.join('\n'));
    fs.writeFileSync(path.join(root,'shell-report.json'),JSON.stringify({passed:true,results,errors},null,2));
    console.log(JSON.stringify({passed:true,sizes:results.map(r=>[r.width,r.height]),errors}));
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exit(1);});
