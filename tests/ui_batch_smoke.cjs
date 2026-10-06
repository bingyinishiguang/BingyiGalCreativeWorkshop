const e2e = require('./ui_e2e_helper.cjs');
const { chromium } = e2e;

(async () => {
  const browser = await chromium.launch({ executablePath: e2e.requireBrowser(), headless: true });
  const page = await browser.newPage({ viewport: { width: 1366, height: 820 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.goto(process.argv[2]);
    await page.waitForFunction(() => document.querySelector('#preview')?.naturalWidth > 0);
    const layout = await page.evaluate(() => {
      const cards = [...document.querySelectorAll('.action-panel > section')];
      const buttons = ['download', 'open-custom-batch'].map(id => document.getElementById(id));
      return { order: cards.map(card => card.id), within: buttons.every(button => {
        const card = button.closest('.action-card').getBoundingClientRect();
        const box = button.getBoundingClientRect();
        return box.top >= card.top && box.bottom <= card.bottom;
      }) };
    });
    if (layout.order.join() !== 'export-card,custom-batch-card' && layout.order.join() !== ',custom-batch-card') throw new Error('右侧卡片排序错误');
    if (await page.locator('#batch-card').count()) throw new Error('本作精选入口仍在工作台');
    if (!layout.within) throw new Error('按钮仍被卡片裁切');
    await page.screenshot({ path: '工作数据/exports/custom-batch-layout.png' });
    for (const viewport of [{ width: 1366, height: 600 }, { width: 1024, height: 768 }, { width: 360, height: 740 }]) {
      await page.setViewportSize(viewport);
      const within = await page.evaluate(() => ['download', 'open-custom-batch'].every(id => {
        const button = document.getElementById(id).getBoundingClientRect();
        const card = document.getElementById(id).closest('.action-card').getBoundingClientRect();
        return button.top >= card.top && button.bottom <= card.bottom && button.left >= card.left && button.right <= card.right;
      }));
      if (!within) throw new Error(`${viewport.width} × ${viewport.height} 时按钮被裁切`);
    }
    await page.setViewportSize({ width: 1366, height: 820 });
    await page.locator('#open-custom-batch').click();
    await page.locator('#batch-inspector-image').waitFor({ state: 'visible' });
    await page.screenshot({ path: '工作数据/exports/custom-batch-picker.png' });
    if (await page.locator('#batch-inspector-image').evaluate(image => image.naturalWidth) < 100) throw new Error('脸部预览未加载');
    const loaded = await page.locator('#batch-face-grid img[src]').count();
    const totalFaces = await page.locator('#batch-face-grid .batch-face-card').count();
    if (!(loaded > 0 && loaded < totalFaces)) throw new Error(`图片未按需加载：${loaded}/${totalFaces}`);
    await page.locator('#batch-bg-toggle').click();
    if (!await page.locator('#batch-inspector-visual').evaluate(element => element.classList.contains('dark'))) throw new Error('深色背景切换失败');
    await page.locator('#batch-view-full').click();
    await page.locator('#batch-inspector-image').waitFor({ state: 'visible' });
    await page.locator('#batch-view-face').click();
    await page.locator('#batch-add').click();
    if (await page.locator('.batch-queue-row').count() !== 1) throw new Error('第一张未加入清单');
    await page.locator('#close-custom-batch').click();
    await page.locator('#game').selectOption('LimeLightLemonadeJam');
    await page.locator('#open-custom-batch').click();
    if (await page.locator('.batch-queue-row').count() !== 1) throw new Error('未导出的跨作品清单不应自动清空');
    await page.locator('#batch-add').click();
    if (await page.locator('.batch-queue-row').count() !== 2) throw new Error('跨作品清单失败');
    await page.locator('#batch-add').click();
    if (await page.locator('.batch-queue-row').count() !== 2) throw new Error('重复项未去重');
    await page.locator('#batch-start').click();
    await page.waitForFunction(() => document.querySelector('#batch-result')?.textContent?.startsWith('完成：'), null, { timeout: 60000 });
    const result = await page.locator('#batch-result').textContent();
    if (!result.includes('成功 2 张，失败 0 张')) throw new Error(result);
    if (await page.locator('.batch-queue-row').count() !== 0) throw new Error('成功导出后旧清单未清空');
    await page.locator('#close-custom-batch').click();
    await page.locator('#game').selectOption('常轨脱离');
    await page.locator('#open-custom-batch').click();
    if (await page.locator('.batch-queue-row').count() !== 0) throw new Error('重新打开仍残留上次清单');
    await page.screenshot({ path: '工作数据/exports/custom-batch-desktop.png' });
    await page.setViewportSize({ width: 360, height: 740 });
    await page.screenshot({ path: '工作数据/exports/custom-batch-mobile.png', fullPage: true });
    if (errors.length) throw new Error(errors.join('; '));
    console.log(result);
    console.log('未导出时保留跨作品清单、完成后清空、重新打开无旧项；既有导出与预览回归通过');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
