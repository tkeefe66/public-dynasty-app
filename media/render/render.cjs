'use strict';
// Deterministic frame-at-time capture. Input is data, never HTML/code or URLs.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {spawnSync} = require('node:child_process');
const {chromium} = require('playwright');
const sha = data => crypto.createHash('sha256').update(data).digest('hex');
const arg = name => process.argv[process.argv.indexOf(name) + 1];
const input = path.resolve(arg('--episode')), out = path.resolve(arg('--output'));
const e = JSON.parse(fs.readFileSync(input, 'utf8'));
const fail = code => { throw new Error(code); };
let browser;
async function main() {
  fs.mkdirSync(out, {recursive:true});
  if (e.geometry?.width !== 1280 || e.geometry?.height !== 720 || e.geometry?.fps !== 30 || !Number.isFinite(e.duration) || e.duration <= 0 || e.duration > 1200) fail('timeline_invalid');
  const check = spawnSync('/opt/venv/bin/python', ['-c', 'import json,sys;from media.timeline import validate_episode;issues=validate_episode(json.load(open(sys.argv[1])));print(issues);sys.exit(bool(issues))', input], {encoding:'utf8'});
  if (check.status !== 0) fail('timeline_invalid');
  if (e.audio !== 'audio.wav') fail('audio_path_invalid');
  const audio = path.join(out, 'audio.wav');
  if (!fs.existsSync(audio)) fail('audio_missing');
  if (sha(fs.readFileSync(audio)) !== e.audio_sha256) fail('audio_hash_mismatch');
  let css = fs.readFileSync(path.join(__dirname,'style.css'),'utf8');
  for (const [family,file] of Object.entries({Bricolage:'bricolage-grotesque-latin-var.woff2',Geist:'geist-latin-var.woff2',GeistMono:'geist-mono-latin-var.woff2'})) {
    const bytes=fs.readFileSync(path.join(__dirname,'fonts',file));
    if(sha(bytes)!==e.fonts[family]) fail('font_missing');
    css=css.replace(`url(fonts/${file})`,`url(data:font/woff2;base64,${bytes.toString('base64')})`);
  }
  browser=await chromium.launch({headless:true,args:['--no-sandbox','--disable-dev-shm-usage','--disable-background-networking','--disable-extensions']});
  const page=await browser.newPage({viewport:{width:1280,height:720},deviceScaleFactor:1,serviceWorkers:'block'});
  await page.route('**/*',route=>route.abort());
  await page.setContent(fs.readFileSync(path.join(__dirname,'index.html'),'utf8'));
  await page.addStyleTag({content:css});
  await page.evaluate(data=>{window.EPISODE=data;},e);
  await page.addScriptTag({content:fs.readFileSync(path.join(__dirname,'scene.js'),'utf8')});
  const fonts=await page.evaluate(async()=>{
    await Promise.all([document.fonts.load('800 108px Bricolage'),document.fonts.load('600 178px GeistMono'),document.fonts.load('500 30px Geist')]);
    return ['800 108px Bricolage','600 178px GeistMono','500 30px Geist'].every(s=>document.fonts.check(s));
  });
  if(!fonts) fail('font_missing');
  const frames=path.join(out,'frames');fs.mkdirSync(frames,{recursive:true});
  const count=Math.ceil(e.duration*30), issues=new Set();
  const representatives=new Set([0,count-1,...e.scenes.flatMap(s=>[Math.min(count-1,Math.ceil(s.start*30)),Math.min(count-1,Math.ceil((s.start+.6)*30))])]);
  const snapshots=[],geometry=new Map();
  for(let frame=0;frame<count;frame++) {
    const measured=await page.evaluate(t=>window.renderFrame(t),frame/30);
    for(const issue of measured.issues) issues.add(issue);
    for(const row of measured.geometry) {
      const old=geometry.get(row.key);
      if(old) {old.left=Math.min(old.left,row.left);old.right=Math.max(old.right,row.right);old.top=Math.min(old.top,row.top);old.bottom=Math.max(old.bottom,row.bottom);old.samples++;}
      else geometry.set(row.key,{...row,samples:1});
    }
    if(geometry.size>4096) fail('geometry_inventory_exceeded');
    if(issues.size) {fs.writeFileSync(path.join(out,'geometry-error.json'),JSON.stringify([...geometry.values()]));fail([...issues].join(','));}
    const file=path.join(frames,`${String(frame).padStart(7,'0')}.png`);
    await page.screenshot({path:file,animations:'disabled'});
    if(representatives.has(frame)) {
      const name=`frame-${String(frame).padStart(7,'0')}.png`;
      fs.copyFileSync(file,path.join(out,name));snapshots.push({file:name,time:frame/30,sha256:sha(fs.readFileSync(file))});
    }
  }
  await browser.close();browser=null;
  const ffmpeg=spawnSync('/usr/bin/ffmpeg',['-v','error','-nostdin','-protocol_whitelist','file,pipe','-framerate','30','-i',path.join(frames,'%07d.png'),
    '-protocol_whitelist','file,pipe','-i',audio,'-map','0:v:0','-map','1:a:0','-c:v','libx264','-preset','fast','-crf','23','-pix_fmt','yuv420p','-threads','2',
    '-c:a','aac','-b:a','128k','-movflags','+faststart','-y',path.join(out,'video.mp4')],{encoding:'utf8',timeout:1200000});
  if(ffmpeg.status!==0) {fs.writeFileSync(path.join(out,'mux-error.txt'),String(ffmpeg.stderr));fail('mux_failed');}
  fs.writeFileSync(path.join(out,'render.json'),JSON.stringify({renderer_version:e.renderer_version,frame_count:count,fps:30,geometry:e.geometry,
    fonts:e.fonts,layout_issues:[...issues],geometry:[...geometry.values()].map(r=>{const b=r.caption===null?[0,0,1280,716]:[56,0,1224,675];return {...r,bounds:b,margins:[r.left-b[0],r.top-b[1],b[2]-r.right,b[3]-r.bottom]};}),representative_frames:snapshots,input_sha256:sha(fs.readFileSync(input)),
    scripts:Object.fromEntries(['render.cjs','scene.js','style.css','index.html'].map(f=>[f,sha(fs.readFileSync(path.join(__dirname,f)))]))}));
  fs.rmSync(frames,{recursive:true});
}
main().catch(async error=>{if(browser) await browser.close();fs.writeFileSync(path.join(out,'render-error.json'),JSON.stringify({code:error.message}));process.exitCode=1;});
