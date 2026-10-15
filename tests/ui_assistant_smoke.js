/* Run with Tabbit nodejs on an isolated local preview tab. Optional global assistantPreviewUrl. All provider calls below are mocked; no credentials or exported files are created. */
page.on('dialog',dialog=>dialog.accept());
await page.goto(globalThis.assistantPreviewUrl || 'http://127.0.0.1:52878/',{waitUntil:'domcontentloaded'});
await page.locator('#boot-overlay').waitFor({state:'hidden'});
await page.locator('#nav-tools').click();
await page.locator('#open-roughcut').click();
await page.locator('#assistant-ball').click();
await expect(page.locator('#assistant-panel')).toBeVisible();

const errors=[];page.on('pageerror',e=>errors.push(e.message));
await page.evaluate(()=>{const p=cutEditor.snapshot();p.scenes=[{id:'test-scene',blank:true,background:'',duration:4,actors:[]}];p.audioClips=[{id:'test-clip',audio:'test-audio',kind:'dialogue',track:0,start:0,duration:4,sourceStart:0,volume:1,cues:[{start:0,end:1,text:'原文'}],subtitles:true,subtitleStyle:{x:0,y:-.8,size:8,color:'#ffffff'}}];cutEditor.applyTimeline(p);});
await page.route('**/api/assistant/chat',async r=>{const p=r.request().postDataJSON().project;p.audioClips[0].cues[0].text='修改后的字幕';await r.fulfill({json:{message:'字幕已修改',project:p}});});
await page.locator('#assistant-input').fill('把第一条字幕改一下');await page.locator('#assistant-send').click();
await expect(page.locator('#assistant-send')).toBeEnabled();
assert.equal(await page.evaluate(()=>cutEditor.snapshot().audioClips[0].cues[0].text),'修改后的字幕');
await page.locator('#assistant-undo').click();assert.equal(await page.evaluate(()=>cutEditor.snapshot().audioClips[0].cues[0].text),'原文');
await page.route('**/api/assistant/pipeline',async r=>{globalThis.savedProject=r.request().postDataJSON().project;globalThis.savedProject.audioClips[0].cues[0].text='任务字幕';await r.fulfill({json:{job:{id:'mock-job',status:'running',stage:'识别'}}});});
await page.route('**/api/assistant/job?*',async r=>{await new Promise(resolve=>setTimeout(resolve,600));await r.fulfill({json:{id:'mock-job',status:'completed',stage:'完成',logs:[],project:globalThis.savedProject}});});
await page.locator('#assistant-translate').uncheck();await page.locator('#assistant-start').click();
await page.evaluate(()=>{const p=cutEditor.snapshot();p.audioClips[0].cues[0].text='用户同时编辑';cutEditor.applyTimeline(p);});
await expect(page.locator('#assistant-apply')).toBeVisible();await expect(page.locator('#assistant-send')).toBeEnabled();
await page.locator('#assistant-apply').click();assert.equal(await page.evaluate(()=>cutEditor.snapshot().audioClips[0].cues[0].text),'用户同时编辑');
await page.locator('#assistant-input').fill('再修改');await page.locator('#assistant-send').click();await expect(page.locator('#assistant-messages')).toContainText('请先写入或丢弃');
await page.locator('#assistant-discard').click();await expect(page.locator('#assistant-apply')).toBeHidden();
await page.unroute('**/api/assistant/chat');await page.unroute('**/api/assistant/pipeline');await page.unroute('**/api/assistant/job?*');

let config={models:[{id:'testmodel',name:'验收模型',baseUrl:'https://example.test/v1',model:'test',hasApiKey:true}],activeModelId:'testmodel',asr:{modelPath:'F:/models/test',pythonPath:'F:/runtime/python.exe',device:'cpu',computeType:'int8'},translation:{provider:'baidu',appId:'testapp',hasSecret:true}},sent=null;
await page.route('**/api/assistant/settings',async r=>{if(r.request().method()==='POST'){sent=r.request().postDataJSON();config={...sent,models:sent.models.map(m=>{const copy={...m,hasApiKey:true};delete copy.apiKey;return copy;}),translation:{provider:'baidu',appId:sent.translation.appId,hasSecret:true}};}await r.fulfill({json:config});});
await page.locator('#assistant-settings-open').click();await expect(page.locator('#assistant-settings')).toBeVisible();assert.equal(await page.locator('#assistant-api-key').inputValue(),'');assert.equal(await page.locator('#assistant-baidu-secret').inputValue(),'');
await page.locator('#assistant-asr-device').selectOption('cuda');await page.locator('#assistant-asr-compute').selectOption('float16');await page.locator('#assistant-settings-save').click();await expect(page.locator('#assistant-settings-status')).toHaveText('配置已保存');assert.equal(sent.models[0].apiKey,'');assert.equal(sent.translation.secret,'');assert.equal(sent.asr.pythonPath,'F:/runtime/python.exe');assert.equal(sent.asr.device,'cuda');assert.equal(sent.asr.computeType,'float16');
await page.locator('#assistant-settings-close').click();await page.reload({waitUntil:'domcontentloaded'});await page.locator('#boot-overlay').waitFor({state:'hidden'});await page.locator('#nav-tools').click();await page.locator('#open-roughcut').click();await page.locator('#assistant-ball').click();await page.locator('#assistant-settings-open').click();await expect(page.locator('#assistant-settings')).toBeVisible();assert.equal(await page.locator('#assistant-api-key').inputValue(),'');assert.equal(await page.locator('#assistant-asr-device').inputValue(),'cuda');await page.locator('#assistant-settings-close').click();
await page.route('**/api/assistant/chat',async r=>r.fulfill({json:{message:'草稿已生成',exportResult:{path:'F:/output/test-draft'}}}));
let opened='';await page.route('**/api/settings/open-folder',async r=>{opened=r.request().postDataJSON().path;await r.fulfill({json:{ok:true}});});
await page.locator('#assistant-input').fill('输出草稿');await page.locator('#assistant-send').click();await expect(page.locator('#assistant-messages')).toContainText('F:/output/test-draft');await page.getByRole('button',{name:'打开草稿文件夹',exact:true}).click();assert.equal(opened,'F:/output/test-draft');

await page.unroute('**/api/assistant/chat');
await page.route('**/api/assistant/chat',async r=>{const p=r.request().postDataJSON().project;p.durationUs=12345;await r.fulfill({json:{message:'草稿已生成',actions:[{tool:'export_draft',arguments:{}}],project:p,exportResult:{path:'F:/output/export-only'}}});});
const exportBefore=await page.evaluate(()=>JSON.stringify(cutEditor.snapshot()));
await page.locator('#assistant-input').fill('仅输出草稿');await page.locator('#assistant-send').click();await expect(page.locator('#assistant-send')).toBeEnabled();assert.equal(await page.evaluate(()=>JSON.stringify(cutEditor.snapshot())),exportBefore);
await page.unroute('**/api/assistant/chat');
await page.route('**/api/assistant/chat',async r=>{await new Promise(resolve=>setTimeout(resolve,600));await r.fulfill({json:{message:'撤销请求',undo:true}});});
await page.locator('#assistant-input').fill('撤销');await page.locator('#assistant-send').click();await page.evaluate(()=>{const p=cutEditor.snapshot();p.scenes=[{id:'concurrent-scene',blank:true,background:'',duration:9,actors:[]}];cutEditor.applyTimeline(p);});
const concurrentBefore=await page.evaluate(()=>JSON.stringify(cutEditor.snapshot()));await expect(page.locator('#assistant-send')).toBeEnabled();assert.equal(await page.evaluate(()=>JSON.stringify(cutEditor.snapshot())),concurrentBefore);await expect(page.locator('#assistant-messages')).toContainText('未撤销当前项目');
assert.equal(errors.length,0); return {checks:['chat subtitle applied','undo restores subtitle','pipeline concurrent edit protected','pending blocks chat','discard releases result','masked key save/reload','ASR parameters retained','export path visible','open folder target','export-only leaves project unchanged','concurrent edit blocks chat undo'],pageErrors:errors};