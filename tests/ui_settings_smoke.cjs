const e2e = require('./ui_e2e_helper.cjs');
const { chromium } = e2e;

(async () => {
  const browser = await chromium.launch({ executablePath: e2e.requireBrowser(), headless: true });
  const page = await browser.newPage({ viewport: { width: 1366, height: 820 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const settings = { singleMode: 'browser', singlePath: '', batchPath: '',
    defaultBatchPath: 'F:\\Bingyi\\工作数据\\exports', effectiveBatchPath: 'F:\\Bingyi\\工作数据\\exports',
    libraryPath: 'F:\\Bingyi\\工作数据\\exports\\立绘库' };
  let saved = null;
  let singleExport = null;
  await page.route('**/api/settings', async route => {
    if (route.request().method() === 'POST') {
      saved = route.request().postDataJSON();
      Object.assign(settings, saved);
    }
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(settings) });
  });
  await page.route('**/api/export-file', async route => {
    singleExport = route.request().postDataJSON();
    await route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify({ path: 'F:\\Bingyi\\单张\\角色.png' }) });
  });
  try {
    await page.goto(process.argv[2]);
    await page.waitForFunction(() => document.querySelector('#preview')?.naturalWidth > 0);
    await page.locator('#settings-button').click();
    await page.locator('#settings-page').waitFor({ state: 'visible' });
    if (!await page.locator('#settings-mode-button').isVisible()) throw new Error('界面模式入口消失');
    if (!await page.locator('.brand-avatar').isVisible()) throw new Error('创作者头像消失');
    if (await page.locator('#settings-library-path').count()) throw new Error('设置页仍显示立绘库路径');
    await page.locator('input[name="single-save-mode"][value="folder"]').check();
    await page.locator('#single-path').fill('F:\\Bingyi\\单张');
    await page.locator('#batch-path').fill('F:\\Bingyi\\批量');
    await page.locator('#nav-workbench').click();
    await page.locator('#settings-button').click();
    if (await page.locator('#batch-path').inputValue() !== 'F:\\Bingyi\\批量') throw new Error('未保存的设置在切页后丢失');
    await page.locator('#save-settings').click();
    await page.waitForFunction(() => document.querySelector('#settings-status')?.textContent.includes('已保存'));
    if (!saved || saved.singleMode !== 'folder' || saved.batchPath !== 'F:\\Bingyi\\批量') throw new Error('设置保存请求不正确');
    await page.locator('#nav-workbench').click();
    if (await page.locator('#download').textContent() !== '保存当前立绘') throw new Error('单张按钮未随设置更新');
    await page.locator('#download').click();
    await page.waitForFunction(() => document.querySelector('#export-status')?.textContent.includes('已保存'));
    if (!singleExport?.game || singleExport.special !== false) throw new Error('单张文件保存请求不正确');
    await page.locator('#settings-button').click();
    await page.waitForFunction(() => document.querySelector('#settings-status')?.textContent.includes('已就绪'));
    await page.screenshot({ path: '工作数据/exports/settings-desktop-smoke.png' });
    await page.setViewportSize({ width: 360, height: 740 });
    await page.screenshot({ path: '工作数据/exports/settings-mobile-smoke.png', fullPage: true });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);
    if (overflow) throw new Error('设置页窄屏出现水平溢出');
    if (errors.length) throw new Error(errors.join(' | '));
    console.log('设置导航、路径保存、单张保存、隐藏立绘库路径及窄屏布局通过');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
