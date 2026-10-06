//立绘库清理面板的 UI 验收：模拟后端，验"扫描 → 显示数量 → 确认清理"这条交互。
const e2e = require('./ui_e2e_helper.cjs');
const { chromium } = e2e;

const URL_BASE = process.argv[2] || 'http://127.0.0.1:8000';

(async () => {
  const browser = await chromium.launch({ executablePath: e2e.requireBrowser(), headless: true });
  const page = await browser.newPage({ viewport: { width: 1366, height: 900 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));

  const calls = [];
  let scanPayload = { images: 12, thumbs: 4, total: 16, bytes: 3_400_000,
                      preview: ['aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png', 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.webp'] };
  let cleanPayload = { removed: 16, bytes: 3_400_000, total: 16 };

  await page.route('**/api/library/orphans', async route => {
    const body = route.request().postDataJSON();
    calls.push(body.action);
    if (body.action === 'scan') {
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify(scanPayload) });
    } else {
      //清理后应再扫一次，这时返回空
      scanPayload = { images: 0, thumbs: 0, total: 0, bytes: 0, preview: [] };
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify(cleanPayload) });
    }
  });
  //其余接口给最小可用响应，避免初始化失败把整段脚本带崩
  await page.route('**/api/settings', route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ singleMode: 'browser', singlePath: '', batchPath: '', dragPath: '',
      defaultBatchPath: '', effectiveBatchPath: '', libraryPath: '' }) }));
  await page.route('**/api/data-dir', route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ current: 'F:\\Bingyi\\工作数据', default: 'F:\\Bingyi\\工作数据', custom: false, frozen: false }) }));
  await page.route('**/api/packs', route => route.fulfill({
    contentType: 'application/json', body: JSON.stringify({ packs: [] }) }));

  await page.goto(URL_BASE + '/', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.app-header', { timeout: 15000 });

  //进设置页 → 进「立绘库清理」
  await page.evaluate(() => switchPage('settings'));
  const rowText = await page.textContent('[data-settings-open="panel-library-care"] .settings-row-copy strong');
  await page.click('[data-settings-open="panel-library-care"]');
  await page.waitForTimeout(200);

  const panelVisible = await page.isVisible('#panel-library-care');
  const cleanHiddenBefore = await page.getAttribute('#library-orphan-clean', 'hidden');
  const statusBefore = await page.textContent('#library-orphan-status');

  //点扫描
  await page.click('#library-orphan-scan');
  await page.waitForTimeout(300);
  const statusAfterScan = await page.textContent('#library-orphan-status');
  const cleanHiddenAfterScan = await page.getAttribute('#library-orphan-clean', 'hidden');
  const cleanLabel = await page.textContent('#library-orphan-clean');
  const listText = await page.textContent('#library-orphan-list');

  //点取消（不该发 clean）
  await page.click('#library-orphan-cancel');
  await page.waitForTimeout(150);
  const statusAfterCancel = await page.textContent('#library-orphan-status');

  //重新扫 → 确认清理（自动接受 confirm）
  page.on('dialog', dialog => dialog.accept());
  await page.click('#library-orphan-scan');
  await page.waitForTimeout(300);
  await page.click('#library-orphan-clean');
  await page.waitForTimeout(400);
  const statusAfterClean = await page.textContent('#library-orphan-status');

  console.log(JSON.stringify({
    rowText, panelVisible,
    cleanHiddenBefore: cleanHiddenBefore !== null,
    statusBefore,
    statusAfterScan,
    cleanHiddenAfterScan: cleanHiddenAfterScan === null,
    cleanLabel,
    listHasPreview: listText.includes('aaaa'),
    statusAfterCancel,
    statusAfterClean,
    apiCalls: calls,
    pageErrors: errors,
  }, null, 2));

  await browser.close();
})();
