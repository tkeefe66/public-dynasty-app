"use client";

import { useEffect, useState } from "react";
import { SECTIONS } from "./sample";

export function MethodologyToc() {
  const [active, setActive] = useState(SECTIONS[0].id);
  useEffect(() => {
    const obs = new IntersectionObserver(
      (entries) => {
        for (const e of entries) if (e.isIntersecting) setActive(e.target.id);
      },
      { rootMargin: "-30% 0px -60% 0px" },
    );
    for (const s of SECTIONS) {
      const el = document.getElementById(s.id);
      if (el) obs.observe(el);
    }
    return () => obs.disconnect();
  }, []);
  /* Nothing is fixed or sticky, so the contents list is a static column at the
     top of its rail rather than a pinned sidebar. The IntersectionObserver
     stays: marking where the reader is costs nothing and the list is still on
     screen while they read the first sections. Set as a run of whisper labels
     under a heading, the active entry in ink.

     THE RAIL IS DESKTOP-ONLY, AND ALREADY WAS. `hidden lg:block` is unchanged
     by the phone layout — it is left exactly as it stands, deliberately, rather
     than being given a mobile spelling. Below 1024px the second column that
     `app/methodology/page.tsx` lays out does not exist, and a contents list with
     nowhere to sit becomes a duplicate of the destinations it points at. Below
     701px `MethodologySection` supplies those destinations as the accordion's
     own disclosure rows, so the reader gets the same eight targets with no
     duplicated nav. Between the two (701–1023px) the page is what it has always
     been: expanded prose, no rail. */
  return (
    <nav aria-label="Contents" className="hidden self-start lg:block">
      <div className="border-b border-rule pb-1.5 font-mono text-label uppercase tracking-[0.14em] text-dim">
        Contents
      </div>
      <div className="mt-2 space-y-1.5">
        {SECTIONS.map((s) => (
          <a
            key={s.id}
            href={`#${s.id}`}
            aria-current={active === s.id ? "true" : undefined}
            className={`block font-mono text-label uppercase tracking-[0.11em] transition-colors ${
              active === s.id ? "font-bold text-ink" : "text-dim hover:text-ink"
            }`}
          >
            {s.title}
          </a>
        ))}
      </div>
    </nav>
  );
}
