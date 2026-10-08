import type { ReactNode } from "react";

/** Shared publication identity for the dashboard invitation and its destination. */
export function AnalystMasthead({ compact = false, children }: {
  compact?: boolean;
  children?: ReactNode;
}) {
  const Heading = compact ? "h3" : "h1";
  return (
    <div className={`flex flex-wrap items-center justify-between gap-5 bg-ink text-bg ${compact ? "px-5 py-5 sm:px-7" : "rounded-panel px-6 py-7 sm:px-8"}`}>
      <div>
        <Heading className={`font-display font-extrabold tracking-[var(--track-lead)] ${compact ? "text-lead" : "text-nameplate"}`}>
          The Analyst<span aria-hidden="true">.</span>
        </Heading>
        <p className="mt-1 text-prose">Your league. Every week. No one gets a pass.</p>
      </div>
      {children}
    </div>
  );
}
