/* A deterministic frame renderer and local playback/export. No network API. */
"use strict";
const episode = window.EPISODE;
const canvas = document.getElementById("stage");
const ctx = canvas.getContext("2d");
const audio = document.getElementById("audio");
const play = document.getElementById("play");
const seek = document.getElementById("seek");
const exportButton = document.getElementById("export");
const error = document.getElementById("error");
const reduced = matchMedia("(prefers-reduced-motion: reduce)");
const facts = episode.facts;
const labels = ["Opening", "High score", "Biggest margin", "Trade returns", "The payoff", "Sign-off"];
let seconds = 0, playing = false, lastTime = 0, recording = false, recorder;
let captureStream = null, exportFailed = false;
let audioReady = !episode.audio, audioContext, audioNode, audioDestination, downloadURL;
const hasCaptions = true;
const INK = "#17181c", PAPER = "#f5f4ef", DIM = "#c5c7d0", COBALT = "#2f42ff";
const fmt = value => `${Math.floor(value / 60)}:${String(Math.floor(value % 60)).padStart(2, "0")}`;

function fail(message) { error.textContent = message; error.hidden = false; }
function text(value, x, y, size, family = "Bricolage", color = PAPER, weight = 800) {
  ctx.fillStyle = color; ctx.font = `${weight} ${size}px ${family}`; ctx.fillText(value, x, y);
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
  const sentences = scene.narration.match(/[^.!?]+[.!?]?/g).map(sentence => sentence.trim());
  const total = sentences.reduce((sum, sentence) => sum + sentence.split(/\s+/).length, 0);
  const progress = (time - scene.start) / (scene.end - scene.start);
  let words = 0;
  return sentences.find(sentence => { words += sentence.split(/\s+/).length; return words / total > progress; }) || sentences.at(-1);
}
function draw(time, updateUI = true) {
  const index = sceneAt(time), scene = episode.scenes[index];
  const opening = scene.kind === "intro" || scene.kind === "outro";
  const light = scene.kind === "trades" || scene.kind === "share";
  const fg = light ? INK : PAPER, bg = light ? PAPER : INK;
  const age = time - scene.start;
  const enter = reduced.matches ? 1 : 1 - Math.pow(2, -Math.min(age, 1.5) * 6);
  ctx.fillStyle = opening ? COBALT : bg; ctx.fillRect(0, 0, 1280, 720);
  text("DYNASTY BITCH", 56, 60, 26, "GeistMono", fg, 500);
  ctx.textAlign = "right";
  text(`WEEK ${episode.week} / ${episode.season}`, 1224, 60, 24, "GeistMono", fg, 400);
  ctx.textAlign = "left";
  ctx.fillStyle = fg; ctx.globalAlpha = .25; ctx.fillRect(56, 86, 1168, 1); ctx.globalAlpha = 1;
  ctx.save(); ctx.translate(0, (1 - enter) * 26);
  if (opening) {
    lines(scene.title, 56, 225, 108, 1168);
    text("Weekly recap with Cal Mercer", 60, 480, 34, "Geist", PAPER, 500);
  } else if (scene.kind === "score") {
    text(scene.title, 56, 175, 64);
    text(facts.high_points.toFixed(1), 48, 410, 222, "GeistMono", PAPER, 600);
    text("POINTS / LEAGUE HIGH", 64, 465, 28, "GeistMono", DIM, 400);
    // The real score is always shown; only its underline reveals with the beat.
    ctx.fillStyle = PAPER; ctx.fillRect(64, 495, 1148 * enter, 5);
  } else if (scene.kind === "margin") {
    text(facts.winner, 56, 180, 86); text("over", 58, 234, 30, "Geist", DIM, 400);
    text(facts.loser, 56, 335, 86);
    ctx.textAlign = "right"; text(`+${facts.margin.toFixed(1)}`, 1224, 310, 166, "GeistMono", PAPER, 600);
    text("POINT MARGIN", 1212, 369, 26, "GeistMono", DIM, 400); ctx.textAlign = "left";
    text("The week’s widest gap.", 58, 477, 36, "Geist", PAPER, 500);
  } else {
    text(scene.kind === "trades" ? "Mikey’s trades showed up." : "More than half his total.", 56, 180, 64, "Bricolage", INK);
    text(scene.kind === "trades" ? facts.traded_points.toFixed(1) : `${(facts.traded_points / facts.high_points * 100).toFixed(1)}%`, 50, 368, 178, "GeistMono", INK, 600);
    text("FROM TRADE-ACQUIRED STARTERS", 64, 416, 26, "GeistMono", INK, 400);
    const ratio = facts.traded_points / facts.high_points;
    ctx.fillStyle = "#deddd6"; ctx.fillRect(64, 455, 1148, 28);
    ctx.fillStyle = INK; ctx.fillRect(64, 455, 1148 * ratio * enter, 28);
    text(`${facts.traded_points.toFixed(1)} traded`, 64, 520, 26, "GeistMono", INK, 400);
    ctx.textAlign = "right"; text(`${facts.high_points.toFixed(1)} total`, 1212, 520, 26, "GeistMono", INK, 400); ctx.textAlign = "left";
  }
  ctx.restore();
  const caption = captionAt(scene, time);
  ctx.fillStyle = INK; ctx.fillRect(0, 570, 1280, 150);
  if (hasCaptions) lines(caption, 56, 618, 30, 1168, "Geist", PAPER, 500);
  text(episode.audio ? "CAL MERCER / AI VOICE" : "GRAPHICS PREVIEW / NARRATION PENDING", 56, 696, 17, "GeistMono", DIM, 400);
  ctx.fillStyle = "#53545c"; ctx.fillRect(0, 716, 1280, 4);
  ctx.fillStyle = PAPER; ctx.fillRect(0, 716, 1280 * time / 90, 4);
  if (updateUI) {
    document.getElementById("caption").textContent = caption;
    document.getElementById("clock").textContent = `${fmt(time)} / 1:30`;
    seek.value = String(time); seek.setAttribute("aria-valuetext", `${time.toFixed(1)} seconds of 90`);
    document.querySelectorAll(".chapter-list button").forEach((button, i) => button.setAttribute("aria-current", String(index === i)));
  }
}
function pause() {
  playing = false; audio.pause();
  play.textContent = seconds >= 90 ? "Replay" : episode.audio ? "Play recap" : "Play graphics preview";
}
async function resume() {
  if (!audioReady) { fail("Narration is not ready. Check the imported audio file, rebuild, and reload."); return; }
  error.hidden = true;
  if (seconds >= 90) seconds = 0;
  if (episode.audio && seconds < audio.duration) {
    audio.currentTime = seconds;
    try { await audio.play(); } catch { fail("Audio playback was blocked. Press Play again or check the imported file."); return; }
  }
  playing = true; lastTime = performance.now(); play.textContent = "Pause";
}
function setTime(time) {
  seconds = Math.max(0, Math.min(90, time));
  if (episode.audio && audioReady) {
    audio.currentTime = Math.min(seconds, audio.duration);
    if (playing && seconds < audio.duration && audio.paused) {
      audio.play().catch(() => {
        pause(); fail("Audio could not resume after seeking. Press Play to try again.");
      });
    }
  }
  draw(seconds);
}
function tick(now) {
  if (playing) {
    if (episode.audio && audio.seeking) { /* Keep the requested frame until the seek finishes. */ }
    else if (episode.audio && !audio.ended && seconds < audio.duration) seconds = audio.currentTime;
    else seconds += (now - lastTime) / 1000;
    if (seconds >= 90) {
      seconds = 90; pause();
      if (recording && recorder.state === "recording") recorder.stop();
    }
    draw(seconds);
  }
  lastTime = now; requestAnimationFrame(tick);
}
play.addEventListener("click", () => playing ? pause() : resume());
seek.addEventListener("input", () => setTime(Number(seek.value)));
document.addEventListener("visibilitychange", () => {
  if (document.hidden && recording) {
    abortExport("Export stopped because the preview moved to the background. Keep this tab visible and export again.");
  } else if (document.hidden) pause();
});
function cleanupExport() {
  captureStream?.getTracks().forEach(track => track.stop()); captureStream = null;
  recording = false; exportButton.disabled = false; play.disabled = false; seek.disabled = false;
  document.querySelectorAll(".chapter-list button, .script section button").forEach(button => button.disabled = false);
  document.getElementById("export-status").textContent = "";
}
function abortExport(message) {
  exportFailed = true; pause();
  document.getElementById("download").hidden = true;
  if (message) fail(message);
  if (recorder && recorder.state !== "inactive") recorder.stop();
  else cleanupExport();
}
exportButton.addEventListener("click", async () => {
  if (!window.MediaRecorder || !canvas.captureStream) { fail("This browser cannot export video. Open the preview in Chrome and try again."); return; }
  if (!audioReady) { fail("The narration file could not be loaded. Fix it and reload before exporting."); return; }
  pause(); setTime(0); error.hidden = true;
  document.getElementById("download").hidden = true;
  const stream = canvas.captureStream(30);
  captureStream = stream; exportFailed = false;
  try {
    if (episode.audio) {
      if (!audioContext) {
        audioContext = new AudioContext(); audioNode = audioContext.createMediaElementSource(audio);
        audioDestination = audioContext.createMediaStreamDestination();
        audioNode.connect(audioDestination); audioNode.connect(audioContext.destination);
      }
      await audioContext.resume();
      audioDestination.stream.getAudioTracks().forEach(track => stream.addTrack(track.clone()));
    }
    const mimeType = ["video/webm;codecs=vp9,opus", "video/webm;codecs=vp8,opus", "video/webm"].find(type => MediaRecorder.isTypeSupported(type));
    if (!mimeType) throw new Error("No supported WebM encoder");
    recorder = new MediaRecorder(stream, {mimeType, videoBitsPerSecond: 6000000});
    const currentRecorder = recorder;
    const chunks = [];
    recorder.ondataavailable = event => { if (!exportFailed && event.data.size) chunks.push(event.data); };
    recorder.onerror = () => abortExport("Video encoding failed. Reload the preview and try exporting again.");
    recorder.onstop = () => {
      stream.getTracks().forEach(track => track.stop());
      if (recorder !== currentRecorder) return;
      if (exportFailed || seconds < 90 || chunks.length === 0) { cleanupExport(); return; }
      if (downloadURL) URL.revokeObjectURL(downloadURL);
      downloadURL = URL.createObjectURL(new Blob(chunks, {type: "video/webm"}));
      const link = document.getElementById("download");
      link.href = downloadURL; link.download = episode.audio ? "dynasty-bitch-week-4.webm" : "dynasty-bitch-week-4-graphics-preview.webm";
      link.textContent = "Download 90-second video"; link.hidden = false;
      cleanupExport();
    };
    recording = true; exportButton.disabled = true; play.disabled = true; seek.disabled = true;
    document.querySelectorAll(".chapter-list button, .script section button").forEach(button => button.disabled = true);
    document.getElementById("export-status").textContent = "Recording locally for 90 seconds. Keep this tab visible.";
    recorder.start(1000); await resume();
    if (!playing) abortExport();
  } catch (err) {
    abortExport(`Export could not start: ${err.message}. Try Chrome with this tab visible.`);
  }
});

episode.scenes.forEach((scene, index) => {
  const chapter = document.createElement("button"); chapter.type = "button"; chapter.textContent = labels[index];
  chapter.addEventListener("click", () => setTime(scene.start)); document.getElementById("chapters").append(chapter);
  const section = document.createElement("section"), button = document.createElement("button"), paragraph = document.createElement("p");
  button.type = "button"; button.textContent = `${fmt(scene.start)}–${fmt(scene.end)}`;
  button.setAttribute("aria-label", `Preview ${labels[index]}`); button.addEventListener("click", () => setTime(scene.start));
  paragraph.textContent = scene.narration; section.append(button, paragraph); document.getElementById("transcript").append(section);
});
const costs = episode.credits;
for (const [label, value] of [["Narration quote", costs.quoted_credits == null ? "Not quoted" : `${costs.quoted_credits} credits`], ["Known charges", `${costs.known_charged_credits} credits`], ["Attempts", costs.attempts], ["Unresolved charges", costs.unsettled_attempts]]) {
  const row = document.createElement("div"), dt = document.createElement("dt"), dd = document.createElement("dd");
  dt.textContent = label; dd.textContent = String(value); row.append(dt, dd); document.getElementById("costs").append(row);
}
document.getElementById("source").textContent = episode.source;
if (episode.audio) {
  audio.src = episode.audio.file;
  audio.addEventListener("loadedmetadata", () => {
    audioReady = Number.isFinite(audio.duration) && audio.duration >= 75 && audio.duration <= 90;
    if (!audioReady) fail(`Narration is ${audio.duration.toFixed(1)} seconds. This cut accepts 75–90 seconds without cutting or stretching speech. Revise the take or timeline before export.`);
    document.getElementById("media-state").textContent = audioReady ? "Narration attached. Check captions and scene timing before export." : "Narration duration needs attention.";
    play.textContent = "Play recap"; exportButton.textContent = "Export recap";
  });
  audio.addEventListener("error", () => { audioReady = false; pause(); fail("Narration could not be read. Import a valid audio file, rebuild, and reload."); });
}
reduced.addEventListener("change", () => draw(seconds));
// Deterministic frames for export/QA; these never submit external work.
window.recapPilot = {setTime, draw, get time() {return seconds;}, get playing() {return playing;}};
Promise.all([document.fonts.load("800 108px Bricolage"), document.fonts.load("600 178px GeistMono"), document.fonts.load("500 30px Geist")]).then(() => draw(seconds));
draw(0); requestAnimationFrame(tick);
