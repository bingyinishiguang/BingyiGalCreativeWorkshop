const assert=require('node:assert/strict'),fs=require('fs'),path=require('path'),e2e=require('./ui_e2e_helper.cjs');
(async()=>{
 const browser=await e2e.chromium.launch({executablePath:e2e.requireBrowser(),headless:true});
 const page=await browser.newPage({viewport:{width:1366,height:900}}),errors=[];
 page.on('pageerror',error=>errors.push(error.message));
 try{
  await page.goto(process.argv[2]);await page.locator('#boot-overlay').waitFor({state:'hidden'});
  await page.locator('#settings-button').click();await page.locator('#open-localtts').click();
  await page.waitForFunction(()=>document.querySelector('#tts-reference')?.value);
  const reference=await page.locator('#tts-reference').inputValue();
  assert.equal(await page.locator('#tts-textLanguage option').count(),6);
  await page.locator('#tts-preset summary').click();
  await page.locator('#tts-test').click();await page.waitForFunction(()=>document.querySelector('#tts-status').textContent.includes('已连接 api_v2'));
  await page.locator('#tts-preset summary').click();
  await page.locator('#tts-title').fill('日语配音测试');await page.locator('#tts-text').fill('こんにちは。今日は時間がありますか？');
  await page.locator('#tts-textLanguage').selectOption('ja');await page.locator('#tts-generate').click();
  await page.waitForFunction(()=>document.querySelector('#tts-status').textContent.includes('配音已生成'),{},{timeout:240000});
  await page.waitForFunction(()=>document.querySelector('#tts-player').duration>0);
  const count=await page.locator('.tts-take').count();assert(count>=2);
  await page.locator('[data-listen]').first().click();await page.waitForFunction(()=>!document.querySelector('#tts-player').paused);
  const downloaded=page.waitForEvent('download');await page.locator('[data-download]').first().click();assert((await downloaded).suggestedFilename().endsWith('.wav'));
  await page.locator('#tts-back').click();await page.locator('#open-localtts').click();assert.equal(await page.locator('.tts-take').count(),count);
  await page.locator('#tts-preset summary').click();await page.locator('#tts-reference').fill('Z:/missing.wav');await page.locator('#tts-generate').click();
  await page.waitForFunction(()=>document.querySelector('#tts-status').textContent.includes('参考音频'));
  assert.equal(await page.locator('.tts-take').count(),count);
  await page.locator('#tts-reference').fill(reference);await page.locator('#tts-save').click();
  await page.locator('#tts-preset summary').click();
  fs.mkdirSync(process.argv[3],{recursive:true});await page.screenshot({path:path.join(process.argv[3],'voice-studio.png'),fullPage:true});
  assert.deepEqual(errors,[]);console.log('PASS: real generation, audition, download, navigation, failed retry protection');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
