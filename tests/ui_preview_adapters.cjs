const e2e = require('./ui_e2e_helper.cjs');
const { chromium } = e2e;

(async () => {
  const browser = await chromium.launch({ executablePath: e2e.requireBrowser(), headless: true });
  const page = await browser.newPage({ viewport: { width: 1366, height: 800 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.goto(process.argv[2]);
    const catalog = await page.evaluate(() => fetch('/api/catalog').then(response => response.json()));
    const games = ['常轨脱离', 'LimeLightLemonadeJam', Object.keys(catalog).find(name => !['常轨脱离', 'LimeLightLemonadeJam'].includes(name))];
    for (const [index, game] of games.entries()) {
      let choice;
      for (const [character, data] of Object.entries(catalog[game].characters)) {
        const body = Object.keys(data.bodies).find(name => data.bodyCategories[name] === 'normal' && data.bodies[name].length);
        if (body) { choice = { character, body }; break; }
      }
      await page.locator('#game').selectOption(game);
      await page.locator('#character').selectOption(choice.character);
      await page.locator('#body').selectOption(choice.body);
      await page.locator('#open-custom-batch').click();
      await page.locator('#batch-inspector-image').waitFor({ state: 'visible' });
      await page.locator('#batch-inspector-visual').screenshot({ path: `工作数据/exports/expression-preview-${['png', 'pbd', 'txt'][index]}.png` });
      await page.locator('#close-custom-batch').click();
    }
    if (errors.length) throw new Error(errors.join('; '));
    console.log('三种适配器的浏览器表情细节预览均可显示');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
