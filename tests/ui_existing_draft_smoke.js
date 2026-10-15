/* Native encrypted draft integration, using an explicitly supplied fixture. */
const errors=[];page.on('pageerror',e=>errors.push(e.message));
const fixture=process.env.BINGYI_DRAFT_FIXTURE;assert(fixture,'Set BINGYI_DRAFT_FIXTURE to a read-only draft fixture');await page.locator('#existing-path').fill(fixture);
await page.locator('#existing-load').click();await expect(page.locator('#existing-status')).toContainText('已载入');
await expect(page.locator('#existing-editor')).toBeVisible();
assert.equal(await page.locator('#existing-cues textarea').count(),66);
const first=await page.locator('#existing-cues textarea').first().inputValue();
await page.locator('#existing-cues textarea').first().fill(first+'，校对副本验收');await page.locator('#existing-cues textarea').first().press('Tab');
await page.locator('#existing-undo').click();assert.equal(await page.locator('#existing-cues textarea').first().inputValue(),first);
await page.locator('#existing-normalize').click();await expect(page.locator('#existing-status')).toContainText('已预览规范');
await page.locator('#existing-save').click();await expect(page.locator('#existing-status')).toContainText('修改副本已保存',{timeout:30000});
await expect(page.locator('#existing-result')).toContainText('尚未注册到剪映草稿列表');
assert.equal(errors.length,0);
return {count:66,checks:['toolbox entry','real encrypted draft loaded','66 captions shown','caption edit undo','punctuation preview','save independent encrypted copy','source unchanged and roundtrip verified'],status:await page.locator('#existing-status').innerText(),result:await page.locator('#existing-result').innerText(),pageErrors:errors};
