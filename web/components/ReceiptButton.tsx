"use client";

import { useEffect, useRef, useState } from "react";
import { Mark as Icon } from "./furniture/Mark";

/** One-tap group-chat receipt: composes `claim\nabsolute-url` at tap time.
 *  Coarse-pointer devices with the Web Share API get the share sheet
 *  (straight to the group chat); everyone else gets the clipboard with a
 *  brief inline confirmation. Quiet mono affordance per the receipts voice. */
export function ReceiptButton({ claim, path }: { claim: () => string; path: () => string }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  const timer = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => () => clearTimeout(timer.current), []);

  function flash(next: "copied" | "failed") {
    setState(next);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setState("idle"), 2000);
  }

  async function onTap() {
    // `window.location.origin` is safe here: middleware.ts 308-redirects every
    // page request to CANONICAL_HOST (e.g. ffbdynasty.com) before it ever
    // reaches a client component, so by the time this runs the browser's
    // origin is already the canonical one (see middleware.ts + README's
    // CANONICAL_HOST entry).
    const text = `${claim()}\n${new URL(path(), window.location.origin).href}`;
    const coarse = typeof window.matchMedia === "function" && window.matchMedia("(pointer: coarse)").matches;
    if (coarse && typeof navigator.share === "function") {
      // Share-sheet cancel is not a failure — no state change either way.
      navigator.share({ text }).catch(() => {});
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
      flash("copied");
    } catch {
      flash("failed");
    }
  }

  return (
    <button
      type="button"
      onClick={onTap}
      className="shrink-0 whitespace-nowrap font-mono text-label uppercase tracking-widest text-dim hover:text-ink transition-colors px-2 py-2"
    >
      {state === "copied" ? (
        <span className="inline-flex items-center gap-1.5" role="status">
          <Icon name="done" size={12} className="text-dim" />
          <span className="text-pos-strong">Copied</span>
        </span>
      ) : state === "failed" ? (
        <span className="inline-flex items-center gap-1.5" role="status">
          <Icon name="alert" size={12} className="text-dim" />
          <span className="text-neg-strong">Copy failed</span>
        </span>
      ) : (
        <span className="inline-flex items-center gap-1.5">
          <Icon name="copy" size={12} className="text-dim" />
          copy receipt
        </span>
      )}
    </button>
  );
}
