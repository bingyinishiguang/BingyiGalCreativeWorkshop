/* Isolated settings only. No model connection or provider request is made. */
await page.locator('#existing-config').click();await expect(page.locator('#assistant-settings')).toBeVisible();
await page.locator('#assistant-model-new').click();
await page.locator('#assistant-model-name').fill('延迟保存验收模型');await page.locator('#assistant-model-id').fill('isolated-model');await page.locator('#assistant-base-url').fill('https://example.invalid/v1');
await page.route('**/api/assistant/settings',async route=>{if(route.request().method()==='POST')await new Promise(resolve=>setTimeout(resolve,1200));await route.continue();});
await page.locator('#assistant-settings-save').click();await expect(page.locator('#assistant-settings-status')).toHaveText('配置已保存');await expect(page.locator('#existing-model')).toContainText('延迟保存验收模型');
await page.locator('#assistant-model-delete').click();await expect(page.locator('#assistant-settings-status')).toHaveText('配置已删除');await expect(page.locator('#existing-model')).not.toContainText('延迟保存验收模型');
await page.locator('#assistant-settings-close').click();await page.unroute('**/api/assistant/settings');
return {checks:['model list refresh follows actual save completion','model deletion refreshes workbench','no external API test invoked']};
