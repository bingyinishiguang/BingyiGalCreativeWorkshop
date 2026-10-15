async function mockComposer(page) {
  const catalog = {
    '测试作品': {
      characters: {
        '普通角色': {bodies: {'校服': ['01']}, bodyCategories: {'校服': 'normal'}}
      }
    }
  };
  await page.route('**/api/catalog', route => route.fulfill({json:catalog}));
  const image = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScL/nwAAAABJRU5ErkJggg==','base64');
  await page.route('**/api/preview?*', route => route.fulfill({contentType:'image/png',body:image}));
}
module.exports = {mockComposer};
