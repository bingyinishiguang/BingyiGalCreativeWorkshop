/* Real local progress APIs, except one intentionally conflicting write. */
await page.locator('#existing-style summary').first().click();
await page.locator('#existing-auto-save').check();
const cue=page.locator('#existing-cues textarea[data-cue-index="0"]');
await cue.fill('输入时即可自动保存');
await expect(page.locator('#existing-progress-status')).toHaveText('进度已保存',{timeout:12000});
assert.equal(await cue.inputValue(),'输入时即可自动保存');
assert(await cue.evaluate(el=>el===document.activeElement),'Auto-save must not steal input focus');
await page.evaluate(()=>document.querySelector('#existing-source').open=true);await page.locator('#existing-load').click();await expect(page.locator('#existing-status')).toContainText('已恢复保存的编辑进度');assert.equal(await cue.inputValue(),'输入时即可自动保存');
// Simulate another window winning the revision without changing the original draft.
const source=await page.locator('#existing-path').inputValue();
await page.evaluate(async path=>{
  const api=window.cutEditor.api;
  const other=await api('/api/existing-draft/load',{path});
  await api('/api/existing-draft/progress-save',{sessionId:other.sessionId,trackIndex:1,revision:other.progress.revision,tracks:other.progress.tracks.map(t=>t.trackIndex===1?{...t,texts:['其他窗口的最新校对',...t.texts.slice(1)]}:t)});
},source);
await cue.fill('本窗口尚未保存的校对');
await expect(page.locator('#existing-progress-status')).toHaveText('自动保存暂停，进度未保存',{timeout:12000});
await expect(page.locator('#existing-status')).toContainText('其他窗口');
assert.equal(await cue.inputValue(),'本窗口尚未保存的校对');
await expect(page.locator('#existing-reload-recover')).toBeVisible();await page.locator('#existing-reload-recover').click();
await expect(page.locator('#existing-status')).toContainText('本页旧编辑备份');assert.equal(await cue.inputValue(),'其他窗口的最新校对');
const backup=await page.locator('#existing-status').textContent();assert(backup.includes('recovery-backups'));
await cue.fill('');await expect(page.locator('#existing-progress-status')).toHaveText('自动保存暂停，进度未保存',{timeout:12000});await expect(page.locator('#existing-status')).toContainText('字幕内容不正确');
await cue.fill('修正空字幕后保存');await page.locator('#existing-progress-save').click();await expect(page.locator('#existing-progress-status')).toHaveText('进度已保存');
await page.locator('#existing-auto-save').uncheck();await cue.fill('离开页面前的编辑');await page.locator('#existing-back').click();await expect(page.getByRole('heading',{name:'工具箱',exact:true})).toBeVisible();
await page.getByRole('button',{name:/^已有剪映草稿修改/}).click();await page.evaluate(()=>document.querySelector('#existing-source').open=true);await page.locator('#existing-load').click();await expect(page.locator('#existing-status')).toContainText('已恢复保存的编辑进度');assert.equal(await cue.inputValue(),'离开页面前的编辑');
return {checks:['auto-save while input remains focused','auto-save reload recovery','other-window conflict detected','unsaved text retained','backup then reload preserves both versions','empty text pauses auto-save','manual correction resumes saving','back-to-toolbox saves progress'],backup};
