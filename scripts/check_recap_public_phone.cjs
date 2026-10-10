/* Synthetic local API only; exact 390px viewport with installed Chrome. */
const path = require('node:path');
const fs = require('node:fs');
const net = require('node:net');
const { spawn } = require('node:child_process');
const root = path.resolve(__dirname, '..');
const { chromium } = require(path.join(root, 'web/node_modules/@playwright/test'));
const [origin, token, output] = process.argv.slice(2);
if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(origin) || !/^[A-Za-z0-9_-]{43}$/.test(token)) throw new Error('Synthetic localhost API required');

(async () => {
  const port = await new Promise(resolve => {
    const socket = net.createServer().listen(0, '127.0.0.1', () => {
      const value = socket.address().port; socket.close(() => resolve(value));
    });
  });
  const log = fs.openSync(path.join(output, 'next.log'), 'w');
  const web = spawn(process.execPath, [path.join(root,'web/node_modules/next/dist/bin/next'), 'dev', '-p', String(port)], {
    cwd:path.join(root,'web'), stdio:['ignore',log,log], env:{...process.env, API_URL:origin,
      AUTH_SECRET:'synthetic-local-phone-test-secret-only', NEXT_TELEMETRY_DISABLED:'1'}});
  let browser;
  try {
    const url = `http://127.0.0.1:${port}/share/analyst/${token}`;
    let ready = false;
    for (let i=0;i<90;i++) {
      try { if ((await fetch(url)).ok) { ready=true; break; } } catch {}
      await new Promise(resolve=>setTimeout(resolve,500));
    }
    if (!ready) throw new Error('Local share page did not start; inspect next.log');
    browser = await chromium.launch({executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless:true});
    const page = await browser.newPage({viewport:{width:390,height:844},hasTouch:true,isMobile:true});
    await page.goto(url,{waitUntil:'networkidle'});
    await page.waitForFunction(()=>document.querySelector('video')?.readyState>=2);
    const video = page.locator('video');
    await video.evaluate(async element=>{element.muted=true; await element.play();});
    await page.waitForFunction(()=>document.querySelector('video').currentTime>.25);
    await video.evaluate(element=>{element.pause();element.currentTime=1.2;element.textTracks[0].mode='showing';});
    await page.waitForFunction(()=>!document.querySelector('video').seeking && document.querySelector('video').currentTime>=1.19);
    const before = await video.evaluate(element=>({duration:element.duration,seek:element.currentTime,width:element.videoWidth,
      height:element.videoHeight,cues:element.textTracks[0].cues?.length,inline:element.playsInline}));
    if (before.width!==1280 || before.height!==720 || !before.inline) throw new Error('Mobile media compatibility failed');
    for (const format of ['MP4','MP3']) {
      const pending=page.waitForEvent('download');
      await page.getByRole('link',{name:new RegExp(`Download ${format}`)}).tap();
      const download=await pending;
      await download.saveAs(path.join(output,`download.${format.toLowerCase()}`));
      const original=fs.readFileSync(path.join(output,format==='MP4'?'video.mp4':'audio.mp3'));
      if (!original.equals(fs.readFileSync(path.join(output,`download.${format.toLowerCase()}`)))) throw new Error('Download bytes changed');
    }
    const metrics=await page.evaluate(()=>({viewport:innerWidth,overflow:document.documentElement.scrollWidth>innerWidth,
      article:document.querySelector('article')?.textContent}));
    if (metrics.viewport!==390 || metrics.overflow || !metrics.article.includes('Correct published roast.')) throw new Error('Phone layout/article failed');
    await page.screenshot({path:path.join(output,'phone-public.png'),fullPage:true});
    console.log(JSON.stringify({media:before,layout:metrics,downloads:'byte-identical MP4/MP3'}));
  } finally {
    if (browser) await browser.close();
    web.kill('SIGTERM');
    await new Promise(resolve=>web.once('exit',resolve));
    fs.closeSync(log);
  }
})().catch(error=>{ console.error(error.message);process.exitCode=1; });
