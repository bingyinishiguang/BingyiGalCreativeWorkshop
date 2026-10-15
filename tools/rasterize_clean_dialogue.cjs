const fs=require('fs'),path=require('path');
const {chromium,requireBrowser}=require('../tests/ui_e2e_helper.cjs');
(async()=>{const browser=await chromium.launch({executablePath:requireBrowser(),headless:true});
try{for(const name of ['dialogue','dialogue-decoration','extended','extended-no-nameplate','narration']){
 const svg=fs.readFileSync(path.resolve(__dirname,'story-kit-source',name+'.svg'));
 const height=name.startsWith('extended')?420:name==='narration'?300:360;
 const page=await browser.newPage({viewport:{width:1920,height}});
 await page.setContent(`<style>html,body{margin:0;background:transparent}img{display:block}</style><img src="data:image/svg+xml;base64,${svg.toString('base64')}">`);
 await page.locator('img').evaluate(async i=>{await i.decode()});
 await page.screenshot({path:path.resolve('ui/assets/story-kit',name+'.png'),omitBackground:true});await page.close();
}}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1});
