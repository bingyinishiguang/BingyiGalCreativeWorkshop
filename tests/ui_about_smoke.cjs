
const e2e = require('./ui_e2e_helper.cjs'), path = require('node:path');
const { chromium } = e2e;

(async () => {
  const browser = await chromium.launch({ executablePath: e2e.requireBrowser(), headless: true });
  const page = await browser.newPage({ viewport: { width: 1366, height: 900 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const openCalls = [];
  await page.route('**/api/settings/open-folder', async route => {
    const body = route.request().postDataJSON();
    openCalls.push(body);
    //Windows 打开 LICENSE.txt 副本，避免无扩展名文件的关联提示。
    if (body.name === 'LICENSE' || body.name === 'LICENSE.txt') {
      await route.fulfill({ contentType: 'application/json',
        body: JSON.stringify({ path: `F:\\...\\BingyiGalCreativeWorkshop\\${body.name}` }) });
    } else {
      await route.fulfill({ status: 400, contentType: 'application/json',
        body: JSON.stringify({ error: '只能打开程序自带的说明文件' }) });
    }
  });
  await page.route('**/api/settings', route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ singleMode: 'browser', singlePath: '', batchPath: '', dragPath: '',
      defaultBatchPath: '', effectiveBatchPath: '', libraryPath: '' }) }));
  await page.route('**/api/data-dir', route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ current: 'F:\\Bingyi\\工作数据', default: 'F:\\Bingyi\\工作数据', custom: false, frozen: false }) }));
  await page.route('**/api/packs', route => route.fulfill({
    contentType: 'application/json', body: JSON.stringify({ packs: [] }) }));

  await page.goto(process.argv[2] + '/', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.app-header', { timeout: 15000 });

  await page.waitForFunction(
    () => (document.getElementById('about-app-line')?.textContent || '') !== '—',
    { timeout: 15000 });
  await page.waitForTimeout(200);

  await page.evaluate(() => switchPage('settings'));
  await page.waitForTimeout(250);
  const rowText = await page.textContent('[data-settings-open="panel-about"] .settings-row-copy strong');
  const rowValue = await page.textContent('#row-value-about');
  await page.click('[data-settings-open="panel-about"]');
  await page.waitForTimeout(250);

  const headerVersion = await page.textContent('#app-version');
  const appLine = await page.textContent('#about-app-line');
  const copyright = await page.textContent('#about-copyright');
  const license = await page.textContent('#about-license');
  const sourceNote = await page.locator('#about-source-note').count();
  const thirdParty = await page.textContent('#about-third-party');
  const sourceDisabled = await page.locator('#open-about-source').count();
  const hasNoWarranty = await page.evaluate(() =>
    document.querySelector('#panel-about').textContent.includes('不提供任何担保'));
  const assert = require('node:assert/strict');
  assert.match(license, /Apache-2\.0/);
  assert.match(headerVersion, /开发中/);
  assert.match(appLine, /开发中/);
  assert.match(rowValue, /开发中/);
  assert(await page.locator('#beta-notice').isHidden());
  assert.equal(await page.locator('#panel-about').evaluate(el=>/AGPL|Affero|获取源代码/.test(el.textContent)), false);
  assert.equal(sourceNote, 0);
  assert.equal(sourceDisabled, 0);
  assert(hasNoWarranty);
  const screenshot = path.join(process.argv[3] || '工作数据/临时/ui-smoke', 'about-panel.png');
  await page.screenshot({ path: screenshot });

  //点「打开 LICENSE 文件」→ 应走白名单成功
  await page.click('#open-license-file');
  await page.waitForTimeout(300);
  const afterOpen = await page.textContent('#about-third-party');


  await page.evaluate(() => openAboutFile('../../sprite_composer.py'));
  await page.waitForTimeout(300);
  const afterEvil = await page.textContent('#about-third-party');

  assert.equal(errors.length, 0, errors.join("\n"));
  assert.match(afterOpen, /已打开/);
  assert.match(afterEvil, /打开失败/);
  console.log(JSON.stringify({
    rowText, rowValue, headerVersion, appLine, copyright, license,
    sourceNote, sourceDisabled, hasNoWarranty,
    afterOpen, afterEvil, openCalls, pageErrors: errors, screenshot,
  }, null, 2));
  await browser.close();
})();
