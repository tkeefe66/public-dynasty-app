// Browser regression tests. Run with the local preview server already running.
const {test, before, after} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {chromium} = require('../../web/node_modules/playwright');
const url = process.env.PILOT_PREVIEW_URL || 'http://127.0.0.1:4821';
let browser;
before(async () => {
  const macChrome = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
  const executablePath = process.env.PILOT_CHROME_PATH || (fs.existsSync(macChrome) ? macChrome : undefined);
  browser = await chromium.launch({executablePath, headless:true});
});
after(async () => { await browser?.close(); });

function silentWav(seconds) {
  const bytes = seconds * 8000 * 2, wav = Buffer.alloc(44 + bytes);
  wav.write('RIFF', 0); wav.writeUInt32LE(36 + bytes, 4); wav.write('WAVEfmt ', 8);
  wav.writeUInt32LE(16, 16); wav.writeUInt16LE(1, 20); wav.writeUInt16LE(1, 22);
  wav.writeUInt32LE(8000, 24); wav.writeUInt32LE(16000, 28); wav.writeUInt16LE(2, 32);
  wav.writeUInt16LE(16, 34); wav.write('data', 36); wav.writeUInt32LE(bytes, 40);
  return wav;
}

test('the preview server honors byte ranges used by media seeking', async () => {
  // Mutation: serving every request as 200/full-file defeats media seeking.
  const page = await browser.newPage();
  try {
    const response = await page.request.get(`${url}/player.js`, {headers:{Range:'bytes=0-9'}});
    assert.equal(response.status(), 206);
    assert.equal((await response.body()).length, 10);
    assert.match(response.headers()['content-range'], /^bytes 0-9\//);
    const invalid = await page.request.get(`${url}/player.js`, {headers:{Range:'bytes=999999999-'}});
    assert.equal(invalid.status(), 416);
  } finally { await page.close(); }
});

test('seeking from the graphics tail resumes real ended audio', async () => {
  // Mutation: set currentTime without restarting an ended media element.
  const page = await browser.newPage();
  try {
    await page.route('**/episode.js', async route => {
      const response = await route.fetch();
      await route.fulfill({response, body: (await response.text()) + '\nwindow.EPISODE.audio={file:"synthetic.wav"};'});
    });
    const wav = silentWav(85);
    await page.route('**/synthetic.wav', route => {
      const range = route.request().headers().range?.match(/bytes=(\d+)-(\d*)/);
      if (!range) return route.fulfill({contentType:'audio/wav', body:wav});
      const start=Number(range[1]), end=range[2] ? Number(range[2]) : wav.length-1;
      return route.fulfill({status:206, contentType:'audio/wav', headers:{'accept-ranges':'bytes','content-range':`bytes ${start}-${end}/${wav.length}`}, body:wav.subarray(start,end+1)});
    });
    await page.goto(url);
    await page.waitForFunction(() => document.querySelector('audio').duration === 85);
    await page.evaluate(() => recapPilot.setTime(88));
    await page.locator('#play').click();
    await page.waitForFunction(() => recapPilot.time > 88.1, {}, {timeout:1500});
    await page.evaluate(() => recapPilot.setTime(20));
    await page.waitForFunction(() => recapPilot.time > 20.1, {}, {timeout:1500});
    assert.equal(await page.evaluate(() => document.querySelector('audio').paused), false);
  } finally { await page.close(); }
});

async function fakeRecorderPage() {
  const page = await browser.newPage();
  await page.addInitScript(() => {
    const capture = HTMLCanvasElement.prototype.captureStream;
    HTMLCanvasElement.prototype.captureStream = function(...args) {
      window.testCapture = capture.apply(this, args); return window.testCapture;
    };
    window.MediaRecorder = class {
      static isTypeSupported() { return true; }
      constructor() { window.testRecorder = this; this.state = 'inactive'; }
      start() { this.state = 'recording'; }
      stop() { this.state = 'inactive'; this.onstop?.(); }
    };
  });
  await page.goto(url);
  await page.locator('#export').click();
  return page;
}

test('encoder failure never exposes a partial export as complete', async () => {
  // Mutation: leaving the success onstop callback active after an encoding error.
  const page = await fakeRecorderPage();
  try {
    await page.evaluate(() => { testRecorder.ondataavailable({data:new Blob(['partial'])}); testRecorder.onerror(); testRecorder.stop(); });
    assert.equal(await page.locator('#download').isVisible(), false);
    assert.equal(await page.evaluate(() => testCapture.getVideoTracks()[0].readyState), 'ended');
    assert.equal(await page.locator('#error').isVisible(), true);
  } finally { await page.close(); }
});

test('background cancellation releases capture tracks and offers no download', async () => {
  // Mutation: replacing onstop without stopping the canvas capture track.
  const page = await fakeRecorderPage();
  try {
    await page.evaluate(() => {
      Object.defineProperty(document, 'hidden', {get:() => true, configurable:true});
      document.dispatchEvent(new Event('visibilitychange'));
    });
    assert.equal(await page.locator('#download').isVisible(), false);
    assert.equal(await page.evaluate(() => testCapture.getVideoTracks()[0].readyState), 'ended');
  } finally { await page.close(); }
});
