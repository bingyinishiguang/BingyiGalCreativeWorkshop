
const e2e = require('./ui_e2e_helper.cjs');
const { chromium } = e2e;

const BASE_BRAND = {
  appName: '冰翼Gal创作工坊', appNameEn: 'BingyiGalCreativeWorkshop', tagline: 'Galgame素材工作台',
  version: '1.0', versionLabel: '', creator: '冰翼逆时光', copyright: '© 2026 冰翼逆时光',
  license: 'Apache-2.0', sourceUrl: '',
  dataDirName: 'BingyiGalCreativeWorkshop',
};

async function check(page, beta, label) {
  await page.unroute('**/api/brand').catch(() => {});
  await page.route('**/api/brand', route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ ...BASE_BRAND, beta }),
  }));
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.app-header', { timeout: 15000 });

  await page.waitForFunction(
    () => (document.getElementById('about-app-line')?.textContent || '') !== '—',
    { timeout: 20000 });
  await page.waitForTimeout(300);
  const hidden = await page.getAttribute('#beta-notice', 'hidden');
  const text = await page.textContent('#beta-notice-text');
  const expiredClass = await page.evaluate(() =>
    document.getElementById('beta-notice').classList.contains('beta-notice-expired'));
  return { label, visible: hidden === null, text: (text || '').trim().slice(0, 80), expiredClass };
}

(async () => {
  const browser = await chromium.launch({ executablePath: e2e.requireBrowser(), headless: true });
  const page = await browser.newPage({ viewport: { width: 1366, height: 900 } });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('dialog', d => d.accept());


  await page.route('**/api/brand', route => route.fulfill({
    contentType: 'application/json', body: JSON.stringify(BASE_BRAND) }));
  await page.goto(process.argv[2] + '/', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.app-header', { timeout: 15000 });

  const results = [];
  results.push(await check(page, { configured: true, deadline: '2099-12-31', expired: false,
    daysLeft: 26000, warn: false, warnDays: 7, message: 'x' }, '还早（不该出现）'));
  results.push(await check(page, { configured: true, deadline: '2099-01-05', expired: false,
    daysLeft: 4, warn: true, warnDays: 7, message: 'x' }, '临近（应出现）'));
  results.push(await check(page, { configured: true, deadline: '2000-01-01', expired: true,
    daysLeft: -30, warn: false, warnDays: 7,
    message: '内测期已结束。这个版本可能已经修好了你现在遇到的问题，建议找作者拿新包。' }, '已过期（应出现且红色）'));
  results.push(await check(page, { configured: false, deadline: '', expired: false,
    daysLeft: null, warn: false, warnDays: 7, message: '' }, '未配置（不该出现）'));


  await page.route('**/api/brand', route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ ...BASE_BRAND, beta: { configured: true, deadline: '2000-01-01',
      expired: true, daysLeft: -30, warn: false, warnDays: 7, message: 'm' } }) }));
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.app-header', { timeout: 15000 });
  await page.waitForFunction(
    () => {
      const bar = document.getElementById('beta-notice');
      return bar && bar.hidden === false;
    },
    { timeout: 20000 });
  const visibleBeforeClose = (await page.getAttribute('#beta-notice', 'hidden')) === null;
  await page.click('#beta-notice-close');
  await page.waitForTimeout(200);
  const visibleAfterClose = (await page.getAttribute('#beta-notice', 'hidden')) === null;

  console.log(JSON.stringify({
    results,
    bannerVisibleBeforeClose: visibleBeforeClose,
    bannerHiddenAfterClose: !visibleAfterClose,
    pageErrors: errors,
  }, null, 2));
  await browser.close();
})();
