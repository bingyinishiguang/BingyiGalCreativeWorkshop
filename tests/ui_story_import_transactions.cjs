const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium, requireBrowser} = require('./ui_e2e_helper.cjs');

(async () => {
  const out = path.resolve(process.argv[3]);
  fs.mkdirSync(out, {recursive:true});
  const browser = await chromium.launch({executablePath:requireBrowser(), headless:true});
  const results = [];
  async function test(name, action) {
    const page = await browser.newPage({viewport:{width:1500,height:1000}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    try {
      await page.goto(process.argv[2]);
      await page.locator('#boot-overlay').waitFor({state:'hidden'});
      await page.locator('#nav-tools').click();
      await page.locator('#open-gal-story').click();
      await page.locator('#gs-demo').click();
      await page.waitForFunction(() => document.querySelectorAll('#gs-list .gs-clip').length === 13);
      await page.waitForFunction(() => !document.querySelector('#gal-story-page').inert);
      await action(page);
      assert.deepEqual(errors, []);
      results.push({name, passed:true});
    } catch (error) {
      results.push({name, passed:false, error:error.message});
      await page.screenshot({path:path.join(out, name+'.png'), fullPage:true});
    } finally {
      await page.close();
    }
  }
  const snapshot = page => page.evaluate(() => JSON.parse(localStorage.getItem('bingyi-gal-story-draft')));
  async function delayedBackground(page) {
    const before = await snapshot(page);
    let started;
    const ready = new Promise(resolve => { started=resolve; });
    let complete;
    const waiting = new Promise(resolve => { complete=resolve; });
    const result = {item:{id:'kit:window-night',kind:'background',name:'Imported scene'}};
    await page.route('**/api/gal-story/pick-asset', async route => {
      started();
      await waiting;
      await route.fulfill({json:result});
    });
    await page.locator('#gs-settings-tab').click();
    await page.locator('[data-settings-section="appearance"] > summary').click();
    await page.locator('#gs-import-background').click();
    await ready;
    return {before, complete};
  }
  await test('background-keeps-original-clip', async page => {
    const {before, complete} = await delayedBackground(page);
    await page.locator('#gs-list .gs-clip').nth(1).click();
    complete();
    await page.waitForFunction(() => document.querySelector('#gs-status').textContent.includes('素材已导入'));
    const after = await snapshot(page);
    assert.equal(after.clips[0].backgroundId, 'kit:window-night');
    assert.equal(after.clips[1].backgroundId, before.clips[1].backgroundId);
  });
  await test('background-does-not-change-new-project', async page => {
    const {complete} = await delayedBackground(page);
    await page.locator('#gs-new').click();
    await page.waitForFunction(() => document.querySelector('#gs-name').value === '新剧情' && !document.querySelector('#gal-story-page').inert);
    await page.locator('#gs-add').click();
    const before = await snapshot(page);
    complete();
    await page.waitForFunction(() => document.querySelector('#gs-status').textContent.includes('导入'));
    const after = await snapshot(page);
    assert.deepEqual(after.clips, before.clips);
  });
  await test('audio-keeps-original-clip', async page => {
    const item={id:'f'.repeat(32),name:'Imported audio',kind:'dialogue',duration:2,cues:[]};
    await page.route('**/api/audio/pick', route => route.fulfill({json:{paths:['voice.wav']}}));
    let started, complete;
    const ready=new Promise(resolve => {started=resolve;});
    const waiting=new Promise(resolve => {complete=resolve;});
    await page.route('**/api/audio/import', async route => {started();await waiting;await route.fulfill({json:{results:[{item}]}});});
    const before=await snapshot(page);
    await page.locator('#gs-audio-import').click();
    await ready;
    await page.locator('#gs-list .gs-clip').nth(1).click();
    complete();
    await page.waitForFunction(() => document.querySelector('#gs-status').textContent.includes('音频已导入'));
    const after=await snapshot(page);
    assert.equal(after.clips[0].voiceId,item.id);
    assert.equal(after.clips[0].voiceText,before.clips[0].text);
    assert.equal(after.clips[1].voiceId,before.clips[1].voiceId);
  });
  await browser.close();
  fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(results,null,2));
  console.log(JSON.stringify(results));
  if(results.some(result => !result.passed)) process.exitCode=1;
})().catch(error => {console.error(error);process.exitCode=1;});
