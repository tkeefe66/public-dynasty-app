"use client";

import { useEffect, useRef } from "react";
import { usePathname } from "next/navigation";

/**
 * Fire-and-forget pageview telemetry. Beacons the current pathname to
 * /api/events on every route change (and initial mount). Same-origin, so the
 * Next proxy attaches the backend token; anonymous beacons 401 and are dropped.
 * Sends only the pathname (no query string). Renders nothing.
 */
export function Telemetry() {
  const pathname = usePathname();
  const last = useRef<string | null>(null);

  useEffect(() => {
    if (!pathname || pathname === last.current) return;
    last.current = pathname;
    const body = JSON.stringify({ path: pathname });
    try {
      if (typeof navigator !== "undefined" && navigator.sendBeacon) {
        navigator.sendBeacon("/api/events", new Blob([body], { type: "application/json" }));
      } else {
        void fetch("/api/events", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body,
          keepalive: true,
        });
      }
    } catch {
      // Telemetry must never break navigation.
    }
  }, [pathname]);

  return null;
}
