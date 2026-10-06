const assert=require('node:assert/strict'),fs=require('fs'),path=require('path'),e2e=require('./ui_e2e_helper.cjs');
(async()=>{
 const browser=await e2e.chromium.launch({executablePath:e2e.requireBrowser(),headless:true});
 const out=process.argv[3],component=path.resolve(process.argv[4]);fs.mkdirSync(out,{recursive:true});
 const p=await browser.newPage({viewport:{width:1366,height:900}}),errors=[];p.on('pageerror',e=>errors.push(e.message));p.setDefaultTimeout(180000);
 try{
  await p.goto(process.argv[2]);await p.locator('#boot-overlay').waitFor({state:'hidden'});
  await p.locator('#settings-button').click();await p.locator('#open-localtts').click();
  await p.waitForFunction(()=>document.querySelector('#tts-component-info').textContent.length>0);
  if((await p.locator('#tts-component-info').textContent()).includes('已连接配音组件'))await p.locator('#tts-component-disconnect').click();
  await p.waitForFunction(()=>document.querySelector('#tts-component-info').textContent.includes('选择组件'));
  assert.deepEqual(await p.locator('#tts-sampleSteps option').evaluateAll(a=>a.map(x=>x.value)),['16','32']);
  assert.equal(await p.locator('#tts-sampleSteps').inputValue(),'32');
  await p.locator('#tts-sampleSteps').selectOption('16');
  await p.locator('#tts-speed').fill('0.9');
  await p.locator('#tts-fragmentInterval').fill('0.7');
  await p.locator('[data-listen]').first().click();
  await p.waitForFunction(()=>document.querySelector('#tts-player').duration>0&&!document.querySelector('#tts-player').paused);
  const duration=await p.locator('#tts-player').evaluate(a=>a.duration);assert(duration>0);
  //Only the native folder picker is substituted; real validation/persistence execute on the server.
  await p.route('**/api/localtts/component-pick',async r=>r.fulfill({response:await r.fetch({url:new URL('/api/localtts/component-select',p.url()).href,postData:JSON.stringify({root:component}),timeout:180000})}));
  await p.locator('#tts-component-pick').click();
  await p.waitForFunction(()=>document.querySelector('#tts-status').textContent.includes('组件位置已保存'));
  assert((await p.locator('#tts-component-info').textContent()).includes(component));
  await p.reload();await p.locator('#boot-overlay').waitFor({state:'hidden'});await p.locator('#settings-button').click();await p.locator('#open-localtts').click();
  await p.waitForFunction(()=>document.querySelector('#tts-component-info').textContent.includes('已连接配音组件'));
  await p.locator('#tts-component-disconnect').click();await p.waitForFunction(()=>document.querySelector('#tts-status').textContent.includes('已断开组件'));
  assert.equal(await p.locator('.tts-take').count(),1);
  await p.locator('[data-listen]').click();await p.waitForFunction(()=>!document.querySelector('#tts-player').paused);
  await p.screenshot({path:path.join(out,'no-component-history.png'),fullPage:true});
  await p.locator('#tts-back').click();await p.locator('#open-roughcut').click();
  const original=await p.evaluate(async()=>{const items=(await cutEditor.api('/api/roughcut/projects')).items;const project=await cutEditor.api('/api/roughcut/project?id='+items[0].id);cutEditor.restore(project);return cutEditor.snapshot();});
  await p.locator('[data-text-index="0"]').click();await p.locator('#editor-voice-tab').click();
  await p.waitForFunction(()=>document.querySelector('#voice-component-info').textContent.includes('未连接配音组件'));
  await p.waitForFunction(()=>document.querySelector('#voice-player').duration>0);
  assert.deepEqual(await p.locator('#voice-sample-steps option').evaluateAll(a=>a.map(x=>x.value)),['16','32']);
  await p.locator('#voice-sample-steps').selectOption('16');
  await p.locator('#voice-fragment-interval').fill('0.7');
  assert.equal(await p.locator('#voice-profile option').count(),1);
  await p.locator('#voice-player').evaluate(a=>a.play());
  await p.waitForFunction(()=>!document.querySelector('#voice-player').paused);
  await p.locator('#voice-mode').selectOption('keep');await p.locator('#voice-preview').click();await p.locator('#voice-apply').waitFor({state:'visible'});
  await p.locator('#voice-apply').click();await p.waitForFunction(()=>document.querySelector('#voice-status').textContent.includes('已应用配音'));
  assert.equal(await p.evaluate(()=>cutEditor.snapshot().id),original.id);
  assert.equal(await p.evaluate(()=>cutEditor.snapshot().textClips[0].id),original.textClips[0].id);
  await p.screenshot({path:path.join(out,'no-component-voice-panel.png'),fullPage:true});
  await p.locator('#cut-save').click();await p.waitForFunction(()=>document.querySelector('#cut-status').textContent.includes('已保存'));
  await p.locator('#cut-export').click();await p.waitForFunction(()=>document.querySelector('#cut-status').textContent.includes('已生成')&&document.querySelector('#cut-status').textContent.includes('秒草稿'));
  await p.screenshot({path:path.join(out,'no-component-timeline-voice.png'),fullPage:true});
  assert.deepEqual(errors,[]);
  fs.writeFileSync(path.join(out,'ui-report.json'),JSON.stringify({passed:true,duration,checks:['component folder selection with native picker substituted','saved selection survives page reload','disconnect retains actual generated audio','history and timeline WAV playback','old take preview/application without component','save/export without component'],pageErrors:errors},null,2));
  console.log('PASS optional component UI, persisted selection, real WAV playback, timeline apply and no-component save/export');
 }catch(e){await p.screenshot({path:path.join(out,'failure.png'),fullPage:true});console.log(await p.evaluate(()=>({tts:document.querySelector('#tts-status')?.textContent,cut:document.querySelector('#cut-status')?.textContent,voice:document.querySelector('#voice-status')?.textContent})));throw e;}
 finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
