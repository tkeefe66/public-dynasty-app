"use client";

import { useState } from "react";
import { recapMediaBase, type RecapMediaInfo } from "@/lib/recap-media";

export function RecapMedia({ token, media, week }: { token: string; media: RecapMediaInfo; week: number }) {
  const [failed, setFailed] = useState(false);
  const base = recapMediaBase(token, media.id);
  const duration = Math.ceil(media.duration_seconds);
  const linkClass = "inline-flex min-h-tap items-center rounded-sm border border-rule px-4 py-2 text-sm font-semibold text-ink";
  return <section aria-label="Watch or download the recap" className="mb-8 space-y-4">
    <div className="flex flex-wrap items-baseline justify-between gap-2">
      <h2 className="font-display text-title font-bold">Watch the recap</h2>
      <span className="font-mono text-sm tabular-nums text-dim">{Math.floor(duration / 60)}:{String(duration % 60).padStart(2, "0")}</span>
    </div>
    <video key={media.id} aria-label={`Week ${week} video recap`} className="aspect-video w-full rounded-panel bg-surface-sunk"
      controls playsInline preload="metadata" poster={`${base}/poster.jpg`} src={`${base}/video.mp4`}
      onError={() => setFailed(true)}>
      <track kind="captions" src={`${base}/captions.vtt`} srcLang="en" label="English" />
      Your browser cannot play this video. Use Download MP4 below.
    </video>
    {failed && <p role="alert" className="text-sm text-body">The video could not be loaded. Reload this page to check whether the link is still available, or try a download below.</p>}
    <div className="flex flex-wrap gap-2">
      <a className={linkClass} href={`${base}/video.mp4?download=true`} download>Download MP4 · {(media.video_bytes / 1000000).toFixed(1)} MB</a>
      <a className={linkClass} href={`${base}/audio.mp3?download=true`} download>Download MP3 · {(media.audio_bytes / 1000000).toFixed(1)} MB</a>
    </div>
    <p className="text-sm text-dim">Cal Mercer is a fictional host with an AI voice. Contains strong language.</p>
  </section>;
}
