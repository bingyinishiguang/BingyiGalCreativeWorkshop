/* Isolated three-cue fixture. Real style, preset, progress and export APIs. */
const failures=[];page.on('pageerror',e=>failures.push(e.message));
await page.locator('[data-style-enable="size"]').check();await page.locator('#existing-style-size').fill('6');
await page.locator('[data-style-enable="color"]').check();await page.locator('#existing-style-color').fill('#ffee33');
await page.locator('[data-style-enable="y"]').check();await page.locator('#existing-style-y').fill('-0.6');
await page.locator('#existing-style-preview').click();await expect(page.locator('#existing-status')).toContainText('3 条样式调整');
await expect(page.locator('#existing-style-status')).toHaveText('沿用草稿原样式');
await expect(page.locator('#existing-proposal')).toContainText('字号 6');
await page.locator('#existing-proposal-apply').click();await expect(page.locator('#existing-style-status')).toContainText('已应用：字号 6');
await expect(page.locator('#existing-progress-status')).toHaveText('进度未保存');
await page.locator('#existing-undo').click();await expect(page.locator('#existing-style-status')).toHaveText('沿用草稿原样式');
await expect(page.locator('#existing-progress-status')).toHaveText('尚未编辑');
await page.locator('[data-style-enable="size"]').check();await page.locator('#existing-style-size').fill('6');
await page.locator('#existing-style-preview').click();await expect(page.locator('#existing-proposal')).toBeVisible();await page.locator('#existing-proposal-apply').click();
await page.locator('#existing-style-preset-name').fill('验收栏目字幕'+Date.now());await page.locator('#existing-style-preset-save').click();await expect(page.locator('#existing-status')).toContainText('已保存在本地');
const preset=await page.locator('#existing-style-presets').inputValue();assert(preset);
await page.locator('#existing-style-reset').click();await expect(page.locator('#existing-proposal')).toContainText('恢复原样式');await page.locator('#existing-proposal-apply').click();await expect(page.locator('#existing-style-status')).toHaveText('沿用草稿原样式');
await page.locator('#existing-style-presets').selectOption(preset);await page.locator('#existing-style-preset-preview').click();await expect(page.locator('#existing-proposal')).toContainText('验收栏目字幕');await page.locator('#existing-proposal-apply').click();await expect(page.locator('#existing-style-status')).toContainText('字号 6');
await page.locator('#existing-track').selectOption('2');await expect(page.locator('#existing-style-status')).toHaveText('沿用草稿原样式');await page.locator('#existing-track').selectOption('1');await expect(page.locator('#existing-style-status')).toContainText('字号 6');
// Loading auto-saves dirty text and style progress before replacing the session.
await page.locator('#existing-cues textarea').first().fill('重新载入前的修改');await page.locator('#existing-cues textarea').first().press('Tab');
await page.evaluate(()=>document.querySelector('#existing-source').open=true);await page.locator('#existing-load').click();await expect(page.locator('#existing-status')).toContainText('已恢复保存的编辑进度');
await expect(page.locator('#existing-style-status')).toContainText('字号 6');assert.equal(await page.locator('#existing-cues textarea').first().inputValue(),'重新载入前的修改');
// A mocked mixed model proposal uses the same real local style-preview/export path.
await page.route('**/api/assistant/settings',r=>r.fulfill({json:{models:[{id:'mock-style-model',name:'模拟样式模型'}],activeModelId:'mock-style-model'}}));
await page.route('**/api/existing-draft/chat',async r=>{const p=r.request().postDataJSON();await r.fulfill({json:{message:'待应用的文字与样式建议',warnings:[],changes:[{cueIndex:1,before:p.texts[1],after:'宁宁，向大家问好'}],stylePatch:{...p.stylePatch,color:'#ffff00'},styleChanges:[{cueIndex:0,before:{color:'#ffffff'},after:{color:'#ffff00'}}]}});});
await page.evaluate(()=>document.querySelector('#existing-source').open=true);await page.locator('#existing-load').click();await expect(page.locator('#existing-model')).toHaveValue('mock-style-model');
await page.locator('#existing-chat-input').fill('译名改宁宁，同时改黄字');await page.locator('#existing-chat-send').click();await expect(page.locator('#existing-proposal')).toContainText('样式：');
await page.locator('#existing-proposal-style-check').uncheck();await page.locator('#existing-proposal-apply').click();await expect(page.locator('#existing-style-status')).not.toContainText('#ffff00');assert.equal(await page.locator('#existing-cues textarea[data-cue-index="1"]').inputValue(),'宁宁，向大家问好');
await page.locator('#existing-undo').click();assert.equal(await page.locator('#existing-cues textarea[data-cue-index="1"]').inputValue(),'yinggaidou 向大家问好。');
await page.locator('#existing-chat-input').fill('只应用黄字样式');await page.locator('#existing-chat-send').click();await expect(page.locator('#existing-proposal-style-check')).toBeChecked();await page.locator('#existing-proposal-rows input[data-index="1"]').uncheck();await page.locator('#existing-proposal-apply').click();await expect(page.locator('#existing-style-status')).toContainText('#ffff00');assert.equal(await page.locator('#existing-cues textarea[data-cue-index="1"]').inputValue(),'yinggaidou 向大家问好。');
await page.locator('#existing-save').click();await expect(page.locator('#existing-status')).toContainText('样式 3 条');await expect(page.locator('#existing-result')).toContainText('条样式：');await expect(page.locator('#existing-progress-status')).toHaveText('进度已保存');
await page.unroute('**/api/existing-draft/chat');await page.unroute('**/api/assistant/settings');assert.equal(failures.length,0);
return {checks:['style preview without mutation','style application','dirty progress','style undo','preset persisted','reset preview','preset application','styles retained per track','auto-save before reload','text/style restored on reload','mixed chat proposal','apply text without style','mixed undo','apply style without text','style export details','progress saved after export'],pageErrors:failures};
