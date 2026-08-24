import React from "react";
import { Mark } from "../controls/Mark.jsx";

/**
 * ONE chrome strip, on a hairline. The ink app bar is retired product-wide:
 * a black band across the top of every screen was the single loudest thing in
 * the old design and it carried almost no information.
 *
 * The league name sits BESIDE the wordmark rather than in the right group.
 * Retiring the ink strip took away the only other persistent chrome, and
 * Trades, Bets and Franchises have no masthead of their own — so the league has
 * to hold identity at the left edge, where the eye lands.
 *
 * Wraps on a phone rather than scrolling; horizontal scroll is banned.
 */
export function TopBar({ wordmark = "Fantasy Analyzer", league, items = [], right, style }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: "8px 14px",
        flexWrap: "wrap",
        padding: "10px var(--pad)",
        borderBottom: "1px solid var(--rule)",
        fontFamily: "var(--font-mono)",
        fontSize: "9.5px",
        letterSpacing: ".1em",
        textTransform: "uppercase",
        color: "var(--dim)",
        ...style,
      }}
    >
      <a href="/" style={{ fontFamily: "var(--font-display)", fontWeight: 800, fontSize: 15, letterSpacing: "-.03em", textTransform: "none", color: "var(--ink)", textDecoration: "none" }}>
        {wordmark}
      </a>
      {league ? (
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6, maxWidth: 190, color: "var(--ink)", fontSize: 10, letterSpacing: ".06em" }}>
          <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{league}</span>
          <Mark name="open" size={11} style={{ color: "var(--dim)" }} />
        </span>
      ) : null}
      <nav style={{ display: "flex", alignItems: "center", gap: "8px 12px", flexWrap: "wrap" }}>
        {items.map((it) => (
          <a
            key={it.label}
            href={it.href || "#"}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 5,
              whiteSpace: "nowrap",
              color: it.on ? "var(--ink)" : "inherit",
              fontWeight: it.on ? 600 : 400,
              textDecoration: "none",
            }}
          >
            {it.icon ? <Mark name={it.icon} size={12} /> : null}
            {it.label}
          </a>
        ))}
      </nav>
      {right ? <span style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 12, flexShrink: 0 }}>{right}</span> : null}
    </div>
  );
}
