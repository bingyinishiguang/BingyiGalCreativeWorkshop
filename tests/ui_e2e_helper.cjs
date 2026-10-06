//界面测试使用 BINGYI_PLAYWRIGHT 与 BINGYI_CHROME 覆盖依赖位置。

const fs = require('fs');
const path = require('path');

function firstExisting(candidates) {
  for (const candidate of candidates) {
    if (!candidate) continue;
    try {
      if (fs.existsSync(candidate)) return candidate;
    } catch (_) { /*权限之类的问题直接跳过*/ }
  }
  return null;
}

function resolvePlaywrightModule() {
  if (process.env.BINGYI_PLAYWRIGHT) return process.env.BINGYI_PLAYWRIGHT;

  //从本文件向上查找本地 Playwright 依赖。
  const local = [];
  let dir = __dirname;
  for (let i = 0; i < 4; i += 1) {
    local.push(path.join(dir, 'node_modules', 'playwright'));
    dir = path.dirname(dir);
  }
  try {
    return require.resolve('playwright');
  } catch (_) { /*继续找*/ }

  return firstExisting(local);
}

function resolveBrowser() {
  if (process.env.BINGYI_CHROME) return process.env.BINGYI_CHROME;

  //playwright 自带的浏览器（最可移植）
  const pwRoot = process.env.PLAYWRIGHT_BROWSERS_PATH
    || (process.env.LOCALAPPDATA ? path.join(process.env.LOCALAPPDATA, 'ms-playwright') : null);
  const bundled = [];
  if (pwRoot) {
    try {
      for (const entry of fs.readdirSync(pwRoot)) {
        if (!entry.startsWith('chromium')) continue;
        for (const flavour of ['chrome-win64', 'chrome-win', 'chrome-headless-shell-win64']) {
          const base = path.join(pwRoot, entry, flavour);
          bundled.push(path.join(base, 'chrome.exe'));
          bundled.push(path.join(base, 'headless_shell.exe'));
        }
      }
    } catch (_) { /*目录不存在就算了*/ }
  }

  const installed = [];
  for (const root of [process.env.ProgramFiles, process.env['ProgramFiles(x86)']]) {
    if (!root) continue;
    installed.push(path.join(root, 'Google', 'Chrome', 'Application', 'chrome.exe'));
    installed.push(path.join(root, 'Microsoft', 'Edge', 'Application', 'msedge.exe'));
  }
  if (process.env.LOCALAPPDATA) {
    installed.push(path.join(process.env.LOCALAPPDATA, 'Google', 'Chrome',
                             'Application', 'chrome.exe'));
  }

  return firstExisting([...bundled, ...installed]) || null;
}

function bail(message) {
  console.error('\n[跳过] ' + message + '\n');
  process.exit(2);
}

const playwrightPath = resolvePlaywrightModule();
if (!playwrightPath) {
  bail('没有找到 playwright。界面冒烟测试需要它：\n'
       + '    npm install playwright\n'
       + '  或用 BINGYI_PLAYWRIGHT 指定它的安装路径。');
}

const playwright = require(playwrightPath);

module.exports = {
  chromium: playwright.chromium,
  resolveBrowser,
  requireBrowser() {
    const browser = resolveBrowser();
    if (!browser) {
      bail('没有找到可用的浏览器（Chrome / Edge / playwright 自带 Chromium）。\n'
           + '  装一个，或用 BINGYI_CHROME 指定 chrome.exe 的完整路径。');
    }
    return browser;
  },
};
