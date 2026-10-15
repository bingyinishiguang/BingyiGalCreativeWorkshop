//验证「关于与许可」页点「打开 LICENSE 文件」真的发出 LICENSE.txt 并成功。
const e2e = require('./ui_e2e_helper.cjs');
const { chromium } = e2e;

(async () => {
  const base = process.argv[2];
  const browser = await chromium.launch({ executablePath: e2e.requireBrowser(), headless: true });
  const page = await browser.newPage({ viewport: { width: 1366, height: 900 } });
  const sent = [];
  page.on('request', r => {
    if (r.url().includes('/api/settings/open-folder')) sent.push(r.postData());
  });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('dialog', d => d.accept());

  await page.goto(base + '/', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.app-header', { timeout: 15000 });
  await page.waitForFunction(
    () => (document.getElementById('about-app-line')?.textContent || '') !== '—',
    { timeout: 25000 });

  await page.evaluate(() => switchPage('settings'));
  await page.waitForTimeout(300);
  await page.click('[data-settings-open="panel-about"]');
  await page.waitForTimeout(300);


  const [response] = await Promise.all([
    page.waitForResponse(r => r.url().includes('/api/settings/open-folder'),
                         { timeout: 20000 }),
    page.click('#open-license-file'),
  ]);
  const body = await response.text().catch(() => '');
  await page.waitForTimeout(500);

  const note = await page.textContent('#about-third-party');
  console.log(JSON.stringify({
    requestBodies: sent,
    response: { status: response.status(), body },
    statusLine: (note || '').trim().slice(0, 120),
    pageErrors: errors,
  }, null, 2));
  await browser.close();
})();
