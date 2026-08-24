"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { getMe, myLeagues, type MyLeague } from "@/lib/api";

interface Props {
  currentLeagueId: string;
  /**
   * Where the trigger is drawn.
   *
   * `masthead` — the league NAME in the stamp band is the picker (the shipped
   * home for it: the league is then stated exactly once per screen). The label
   * takes `labelClassName`, which is where the caller's nameplate tier lands,
   * and type reverses out of the cobalt ground.
   *
   * `chip` — the original mono chip in the chrome strip. Kept as the default so
   * `TopBar`'s existing call site is unchanged by this move.
   */
  variant?: "chip" | "masthead";
  /**
   * The current league's name, when the caller already knows it. `myLeagues()`
   * is an on-mount fetch, so without this the trigger reads "League" until it
   * resolves — tolerable for a chip, not for a masthead whose whole job is to
   * say which league you are in.
   */
  name?: string;
  /** Type classes for the label (the masthead's nameplate tier). */
  labelClassName?: string;
}

/** Jump between your leagues. Hosted in the masthead; see `variant`. */
export function LeagueSwitcher({
  currentLeagueId,
  variant = "chip",
  name,
  labelClassName = "",
}: Props) {
  const router = useRouter();
  const [leagues, setLeagues] = useState<MyLeague[]>([]);
  const [isAdmin, setIsAdmin] = useState(false);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    myLeagues().then(setLeagues).catch(() => {});
    getMe().then((me) => setIsAdmin(me.is_admin)).catch(() => {});
  }, []);

  useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const current = leagues.find((l) => l.league_id === currentLeagueId);
  const label = name ?? current?.name ?? "League";
  const masthead = variant === "masthead";

  return (
    <div ref={ref} className={masthead ? "relative min-w-0" : "relative"}>
      {masthead ? (
        /* A REAL button carrying the nameplate, not a heading with a glyph
         * beside it. `min-h-tap` keeps the effective target at the 44px floor
         * even for the smallest nameplate tier, and the accessible name says
         * what the control DOES — the visible name alone reads as a title.
         *
         * Its own focus ring: the global one is `var(--ringfocus)`, which
         * resolves to cobalt, and a cobalt ring on the cobalt band is not a
         * ring at all. Reversed ink instead, same 2px/2px geometry. */
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-haspopup="menu"
          aria-expanded={open}
          aria-label={`${label} — switch league`}
          className="flex min-h-tap w-full min-w-0 items-center gap-3 text-left text-stamp-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-stamp-ink"
        >
          <span className={`min-w-0 break-words ${labelClassName}`}>{label}</span>
          <span
            aria-hidden="true"
            className={`shrink-0 text-section leading-none text-stamp-ink-dim transition-transform ${open ? "rotate-180" : ""}`}
          >
            ▾
          </span>
        </button>
      ) : (
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-haspopup="menu"
          aria-expanded={open}
          className="flex max-w-[160px] items-center gap-1 font-mono text-figure uppercase tracking-[0.11em] text-dim transition-colors hover:text-ink"
        >
          <span className="truncate">{label}</span>
          <span aria-hidden="true" className={`text-label transition-transform ${open ? "rotate-180" : ""}`}>
            ▾
          </span>
        </button>
      )}
      {/* A solid panel has no stripe, so each row draws its own `--rule`
          hairline (the first row draws none). Popovers get no backdrop
          field. */}
      {open && (
        <div
          role="menu"
          /* Anchored to the trigger's own edge: the chip sits at the right of
             the chrome strip, the masthead nameplate at the left of the band. */
          className={`animate-panel-in absolute top-full z-50 mt-1.5 min-w-[214px] border border-ink bg-bg ${
            masthead ? "left-0" : "right-0"
          }`}
        >
          {leagues.map((l, i) => (
            <button
              key={l.league_id}
              role="menuitem"
              onClick={() => {
                setOpen(false);
                router.push(`/league/${l.league_id}`);
              }}
              className={`flex min-h-tap w-full items-center truncate px-2.5 text-left font-mono text-figure ${
                i > 0 ? "border-t border-rule" : ""
              } ${
                l.league_id === currentLeagueId
                  ? "font-bold text-ink"
                  : "text-dim hover:text-ink"
              }`}
            >
              {l.name ?? `League ${l.league_id}`}
            </button>
          ))}
          <button
            role="menuitem"
            onClick={() => {
              setOpen(false);
              router.push("/");
            }}
            /* The divider is CONDITIONAL and heavier on purpose. `leagues`
             * starts empty and is filled by an effect whose errors are
             * swallowed, so this row is the FIRST one rendered whenever the
             * menu opens before the fetch resolves — or if it never does. An
             * unconditional `border-t` there doubles up against the panel's own
             * top edge. It is `border-ink`, not `border-rule`, because it
             * separates the league LIST from the actions block: a heavier rule
             * opens a new band, a hairline separates within one. */
            className={`flex min-h-tap w-full items-center px-2.5 text-left font-mono text-label uppercase tracking-[0.11em] text-dim hover:text-ink ${
              leagues.length > 0 ? "border-t border-ink" : ""
            }`}
          >
            My Leagues →
          </button>
          {isAdmin && (
            <button
              role="menuitem"
              onClick={() => {
                setOpen(false);
                router.push("/admin");
              }}
              className="flex min-h-tap w-full items-center px-2.5 text-left font-mono text-label uppercase tracking-[0.11em] text-dim hover:text-ink"
            >
              Admin →
            </button>
          )}
        </div>
      )}
    </div>
  );
}
