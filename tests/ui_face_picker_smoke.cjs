const e2e = require('./ui_e2e_helper.cjs');
const { chromium } = e2e;

(async () => {
  const browser = await chromium.launch({ executablePath: e2e.requireBrowser(), headless: true });
  const page = await browser.newPage({ viewport: { width: 1366, height: 800 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.goto(process.argv[2]);
    await page.waitForFunction(() => document.querySelector('#preview')?.naturalWidth > 0);
    await page.locator('#face-browse').click();
    await page.waitForFunction(() => [...document.querySelectorAll('#face-grid img')].some(image => image.naturalWidth > 0));
    const total = await page.locator('#face-grid button').count();
    const loaded = await page.locator('#face-grid img[src]').count();
    if (!(total >= 100 && loaded > 0 && loaded < total)) throw new Error(`表情图片未按需加载：${loaded}/${total}`);
    await page.screenshot({ path: '工作数据/exports/quick-face-picker.png' });
    await page.locator('#face-search').fill('a0050');
    if (await page.locator('#face-grid button:not([hidden])').count() !== 2) throw new Error('编号搜索失效');
    await page.locator('#face-search').press('Enter');
    if (await page.locator('#face').inputValue() !== 'a0050') throw new Error('回车未切换表情');
    for (const game of ['LimeLightLemonadeJam', 'Dracu-Riot']) {
      await page.locator('#game').selectOption(game);
      await page.locator('#face-browse').click();
      await page.waitForFunction(() => [...document.querySelectorAll('#face-grid img')].some(image => image.naturalWidth > 0));
      const choice = await page.locator('#face-grid button').nth(1).locator('.face-tile-name').textContent();
      await page.locator('#face-grid button').nth(1).click();
      if (await page.locator('#face').inputValue() !== choice) throw new Error(`${game} 点击图片未切换表情`);
    }
    if (await page.locator('#open-special').count()) throw new Error('特殊模式入口仍存在');
    const access = await page.evaluate(async () => {
      const query = new URLSearchParams({game: document.querySelector('#game').value,
        character: document.querySelector('#character').value,body: document.querySelector('#body').value,
        face: document.querySelector('#face').value});
      const normal = await fetch('/api/expression-preview?' + query);
      query.set('special','1');
      const removed = await fetch('/api/expression-preview?' + query);
      return [normal.status,removed.status];
    });
    if (access[0] !== 200 || access[1] !== 403) throw new Error(`预览访问控制错误：${access}`);
    await page.setViewportSize({ width: 360, height: 740 });
    await page.locator('#nav-workbench').click();
    await page.locator('#face-browse').click();
    const box = await page.locator('#face-dialog').boundingBox();
    if (box.x < 0 || box.x + box.width > 360) throw new Error('窄屏表情弹窗溢出');
    if (errors.length) throw new Error(errors.join('; '));
    console.log('图片卡片、懒加载、搜索回车、已移除特殊模式的访问控制、窄屏布局通过');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
