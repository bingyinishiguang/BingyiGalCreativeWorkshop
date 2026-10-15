const e2e = require('./ui_e2e_helper.cjs');
const { chromium } = e2e;

(async () => {
  const browser = await chromium.launch({ executablePath: e2e.requireBrowser(), headless: true });
  const page = await browser.newPage({ viewport: { width: 1366, height: 820 } });
  await require('./ui_composer_fixture.cjs').mockComposer(page);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const sample = special => ({ id: special ? 'b'.repeat(32) : 'a'.repeat(32), game: '测试作品',
    character: special ? '特殊角色' : '普通角色', body: special ? '泳衣' : '校服', face: '01',
    category: special ? 'swimwear' : 'normal', width: 320, height: 900,
    savedAt: '2026-09-28T12:00:00+08:00', updatedAt: '2026-09-28T12:00:00+08:00', deletedAt: '',
    displayName: '', note: '', favorite: false, tags: [], missing: false });
  let saved = null;
  let normal = sample(false);
  let inTrash = false;
  let updated = null;
  await page.route('**/api/library?*', async route => {
    const params = new URL(route.request().url()).searchParams;
    const special = params.get('special') === '1';
    const trash = params.get('trash') === '1';
    const item = special ? sample(true) : normal;
    const items = special ? (trash ? [] : [item]) : (trash === inTrash ? [item] : []);
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ items, total: items.length, tags: item.tags }) });
  });
  await page.route('**/api/library/image?*', async route => {
    await route.fulfill({ contentType: 'image/png', body: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScL/nwAAAABJRU5ErkJggg==', 'base64') });
  });
  await page.route('**/api/library/save', async route => {
    saved = route.request().postDataJSON();
    await route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify({ ...normal, path: '工作数据/exports/立绘库/图片/test.png', created: true, duplicate: false, repaired: false }) });
  });
  await page.route('**/api/library/update', async route => {
    updated = route.request().postDataJSON();
    normal = { ...normal, displayName: updated.displayName, note: updated.note, favorite: updated.favorite, tags: updated.tags };
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(normal) });
  });
  await page.route('**/api/library/trash', async route => {
    inTrash = true;
    normal = { ...normal, deletedAt: '2026-09-28T13:00:00+08:00' };
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(normal) });
  });
  await page.route('**/api/library/restore', async route => {
    inTrash = false;
    normal = { ...normal, deletedAt: '' };
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(normal) });
  });
  await page.route('**/api/library/delete', async route => {
    inTrash = false;
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ deleted: true }) });
  });
  await page.route('**/api/settings/open-folder', async route => {
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ path: '工作数据/exports/立绘库' }) });
  });
  try {
    await page.goto(process.argv[2]);
    await page.waitForFunction(() => document.querySelector('#preview')?.naturalWidth > 0);
    await page.locator('#save-library').click();
    if (!saved || !saved.game || saved.special !== false) throw new Error('保存到立绘库请求不正确');
    await page.waitForFunction(() => document.querySelector('#save-library-status')?.textContent.includes('已保存'));
    await page.locator('#nav-library').click();
    await page.locator('.library-tile').waitFor();
    if (!(await page.locator('#library-detail-name').textContent()).includes('普通角色')) throw new Error('图库未显示普通立绘');
    await page.locator('#library-edit-name').fill('开场微笑');
    await page.locator('#library-edit-note').fill('第一集使用');
    await page.locator('#library-edit-tags').fill('开心, 开场');
    await page.locator('#library-edit-favorite').check();
    await page.locator('#library-save-edit').click();
    await page.waitForFunction(() => document.querySelector('#library-detail-name')?.textContent.includes('开场微笑'));
    if (!updated?.favorite || updated.tags.length !== 2) throw new Error('资料编辑请求不正确');
    await page.locator('#library-trash').click();
    await page.locator('#library-confirm-submit').click();
    await page.waitForFunction(() => document.querySelector('#library-empty')?.hidden === false);
    await page.locator('#library-view-trash').click();
    await page.locator('.library-tile').waitFor();
    await page.locator('#library-restore').click();
    await page.waitForFunction(() => document.querySelector('#library-empty')?.hidden === false);
    await page.locator('#library-view-active').click();
    await page.locator('.library-tile').waitFor();
    await page.screenshot({ path: '工作数据/exports/library-desktop-smoke.png' });
    if (await page.locator('#open-special').count()) throw new Error('特殊模式入口仍存在');
    if ((await page.locator('#library-grid').textContent()).includes('特殊角色')) throw new Error('普通图库显示特殊角色');
    await page.setViewportSize({ width: 360, height: 740 });
    await page.screenshot({ path: '工作数据/exports/library-mobile-smoke.png', fullPage: true });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    if (overflow) throw new Error('窄屏图库横向溢出');
    await page.locator('#library-trash').click();
    await page.locator('#library-confirm-submit').click();
    await page.locator('#library-view-trash').click();
    await page.locator('.library-tile').waitFor();
    await page.locator('#library-delete').click();
    if (!(await page.locator('#library-confirm-message').textContent()).includes('无法恢复')) throw new Error('永久删除缺少二次确认警告');
    await page.locator('#library-confirm-submit').click();
    await page.waitForFunction(() => document.querySelector('#library-empty')?.hidden === false);
    if (errors.length) throw new Error(errors.join('; '));
    console.log('保存反馈、资料编辑、回收恢复、永久删除确认、模式隔离及窄屏布局通过');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
