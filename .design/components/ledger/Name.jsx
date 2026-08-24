import React from "react";

/**
 * A franchise or player name. The display face belongs to the CLASS, not to
 * the row: scoping the font to a row silently rendered every card name in
 * --font-sans, so the same franchise was Bricolage on desktop and Geist on a
 * phone — two designs rather than two densities.
 *
 * A name in a row truncates (a fixed column cannot reflow); a name in a card
 * wraps and sets one step larger, because a card is the entry's whole heading.
 */
export function Name({ children, on = "row", style }) {
  const card = on === "card";
  return (
    <span
      style={{
        fontFamily: "var(--font-display)",
        fontWeight: card ? 800 : 700,
        fontSize: card ? 16 : "var(--text-name)",
        letterSpacing: "-.022em",
        color: "var(--ink)",
        ...(card ? null : { whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }),
        ...style,
      }}
    >
      {children}
    </span>
  );
}
