"use client";

import { useState } from "react";
import { Mark as Icon } from "./furniture/Mark";

export function ShareUrlButton() {
  const [copied, setCopied] = useState(false);
  return (
    <button
      onClick={async () => {
        await navigator.clipboard.writeText(window.location.href);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }}
      className="inline-flex items-center gap-1.5 border border-ink px-3 py-1.5 font-mono text-label uppercase tracking-[0.1em] text-dim hover:text-ink"
    >
      <Icon name="share" size={12} className="text-dim" />
      {copied ? "Copied" : "Share"}
    </button>
  );
}
