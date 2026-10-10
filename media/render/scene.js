"use strict";
const episode=window.EPISODE, canvas=document.getElementById("stage"), ctx=canvas.getContext("2d");
const INK="#17181c", PAPER="#f5f4ef", DIM="#c5c7d0", COBALT="#2f42ff";
function text(value, x, y, size, family = "Bricolage", color = PAPER, weight = 800) {
  ctx.fillStyle = color; ctx.font = `${weight} ${size}px ${family}`;
  const m=ctx.measureText(String(value));
  const left=ctx.textAlign === "right" ? x-m.width : x;
  if(left < 0 || left+m.width > 1280 || y-m.actualBoundingBoxAscent < 0 || y+m.actualBoundingBoxDescent > 716) window.layoutIssues.push("text_overflow");
  if(window.inCaption && (y+m.actualBoundingBoxDescent > 675 || m.width > 1168)) window.layoutIssues.push("caption_overflow");
  const matrix=ctx.getTransform();
  const r={key:window.inCaption ? `c:${window.cueIndex}:${window.captionLine++}` : `s:${window.sceneIndex}:${window.textSlot++}`,
    scene:window.sceneIndex,caption:window.inCaption ? window.cueIndex : null,text:String(value),size,family,weight,
    left:left+matrix.e,right:left+m.width+matrix.e,top:y-m.actualBoundingBoxAscent+matrix.f,bottom:y+m.actualBoundingBoxDescent+matrix.f};
  if(r.caption === null || r.text.trim()) window.geometry.push(r);
  ctx.fillText(value, x, y);
}
function lines(value, x, y, size, width, family = "Bricolage", color = PAPER, weight = 800) {
  ctx.font = `${weight} ${size}px ${family}`;
  let offset = 0;
  for (const paragraph of value.split("\n")) {
    let line = "";
    for (const word of paragraph.split(" ")) {
      if (line && ctx.measureText(`${line} ${word}`).width > width) {
        text(line, x, y + offset, size, family, color, weight); offset += size * 1.15; line = word;
      } else line += (line ? " " : "") + word;
    }
    text(line, x, y + offset, size, family, color, weight); offset += size * 1.15;
  }
}
function sceneAt(time) {
  return episode.scenes.findIndex(scene => time >= scene.start && time < scene.end) < 0
    ? episode.scenes.length - 1 : episode.scenes.findIndex(scene => time >= scene.start && time < scene.end);
}
function captionAt(scene, time) {
  return episode.captions.find(cue => time >= cue.start && time < cue.end)?.text || "";
}

function draw(time) {
  const index = sceneAt(time), scene = episode.scenes[index];
  window.sceneIndex=index;window.textSlot=0;window.captionLine=0;
  window.cueIndex=episode.captions.findIndex(c=>time>=c.start && time<c.end);
  const opening = scene.kind === "intro" || scene.kind === "outro";
  const light = !!scene.light;
  const fg = light ? INK : PAPER, bg = opening ? COBALT : light ? PAPER : INK;
  const accent = light ? COBALT : "#a5adff";
  const age = Math.max(0, time - scene.start);
  const enter = 1-Math.pow(2,-Math.min(age,1.5)*6);
  ctx.fillStyle = bg; ctx.fillRect(0,0,1280,720);
  text(episode.title,56,60,26,"GeistMono",fg,500);
  ctx.textAlign="right";text(episode.edition,1224,60,24,"GeistMono",fg,400);ctx.textAlign="left";
  ctx.fillStyle=fg;ctx.globalAlpha=.25;ctx.fillRect(56,86,1168,1);ctx.globalAlpha=1;
  ctx.save();ctx.translate(0,(1-enter)*22);
  if (opening) {
    lines(scene.title,56,230,104,1168,"Bricolage",PAPER);
    text("Weekly recap with Cal Mercer",60,490,34,"Geist",PAPER,500);
  } else if (scene.kind === "status") {
    text("LEAGUE STATUS",58,137,22,"GeistMono",accent,500);
    lines(scene.owner,56,250,80,1168,"Bricolage",fg);
    text(scene.status === "bye" ? "BYE" : "SEASON FINISHED",56,400,66,"GeistMono",fg,600);
  } else {
    text(scene.label.toUpperCase(),58,137,22,"GeistMono",accent,500);
    text(scene.winner,56,214,60,"Bricolage",fg);
    text(scene.loser,706,214,60,"Bricolage",fg);
    text(scene.result === "tie" ? "TIE" : scene.result === "tiebreak_win" ? "TIEBREAK WIN" : "WIN",58,252,20,"GeistMono",accent,500);
    text(scene.result === "tie" ? "TIE" : "LOSS",708,252,20,"GeistMono",light?"#62636b":DIM,400);
    text(scene.winner_points,48,365,120,"GeistMono",fg,600);
    text(scene.loser_points,698,365,120,"GeistMono",fg,500);
    ctx.fillStyle=accent;ctx.fillRect(58,390,530*enter,6);
    ctx.fillStyle=light?"#c9cad2":"#5b5e6b";ctx.fillRect(708,390,530*(scene.loser_points/scene.winner_points)*enter,6);
    const hl=scene.highlights.filter(h=>h.at<=time).at(-1)||scene.highlights[0];
    const pulse=Math.min(1,(time-hl.at)*3);
    ctx.globalAlpha=.5+.5*Math.max(0,pulse);
    text(hl.value,56,486,66,"GeistMono",fg,600);
    text(hl.label,60,532,23,"GeistMono",light?"#50525b":DIM,400);
    ctx.globalAlpha=1;
    ctx.textAlign="right";text("FINAL",1222,485,20,"GeistMono",light?"#50525b":DIM,400);ctx.textAlign="left";
  }
  ctx.restore();
  const caption=captionAt(scene,time);
  ctx.fillStyle=INK;ctx.fillRect(0,570,1280,150);
  window.inCaption=true; lines(caption,56,618,30,1168,"Geist",PAPER,500);
  window.inCaption=false; text("CAL MERCER / FICTIONAL REPORTER / AI VOICE",56,696,17,"GeistMono",DIM,400);
  ctx.fillStyle="#53545c";ctx.fillRect(0,716,1280,4);
  ctx.fillStyle=PAPER;ctx.fillRect(0,716,1280*Math.min(time,episode.duration)/episode.duration,4);

}

window.renderFrame=(t)=>{window.layoutIssues=[];window.geometry=[];draw(t);return {issues:[...new Set(window.layoutIssues)],geometry:window.geometry};};
