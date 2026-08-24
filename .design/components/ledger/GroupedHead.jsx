import React from "react";
import { Row } from "./Row";

/**
 * A two-tier ledger head: a naming tier of spanning caps above a normal
 * `Row variant="head"`. Use it when a wide table's labels run together and
 * nothing tells the reader which columns belong to each other.
 *
 * The 44px label tier is not negotiable — `Row`'s head is 44px SPECIFICALLY
 * so a SortButton's tap target fits (see SortButton: "the 44px target lives on
 * the BUTTON, not the row"). That is why this is a separate shape rather than
 * a Row variant: stacking a naming tier means the head is no longer 44px, and
 * `cols`-repeated-verbatim cannot express a cap that spans tracks.
 *
 * A cap must factor out a genuinely shared word or a real structural family —
 * "Points" over Total/Regular/Playoff/Toilet earns its place because it lets
 * four columns stop printing the same word. "Details" over four unrelated
 * columns is decoration, and this system's rule is that structural devices
 * encode something true about the content.
 *
 * Every column belongs to exactly one group and the spans must SUM to the
 * track count. An ungrouped run takes a capless group (`{ span: 3 }`) rather
 * than being left out — that arithmetic is the only thing keeping each cap
 * over its own columns, and a short sum slides every later cap one left.
 *
 * Caps are never interactive. Sorting lives on the label tier where
 * SortButton already is; a clickable cap would imply sorting a group.
 */
export function GroupedHead({ children, cols, groups, style }) {
  return (
    <div style={{ background: "var(--surface-sunk)", paddingTop: 6, ...style }}>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: cols,
          gap: 10,
          padding: "0 14px",
          height: 18,
          alignItems: "end",
          fontFamily: "var(--font-mono)",
          fontSize: "var(--text-label)",
          fontWeight: 500,
          letterSpacing: ".16em",
          textTransform: "uppercase",
          color: "var(--dim)",
        }}
      >
        {groups.map((g, i) => (
          <span
            key={i}
            style={{
              gridColumn: `span ${g.span}`,
              paddingBottom: 3,
              // The rule spans the group's tracks and their internal gaps but
              // stops at the group boundary — the 10px break between caps is
              // what reads as the division.
              borderBottom: g.label ? "1px solid var(--rule-strong)" : undefined,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {g.label || ""}
          </span>
        ))}
      </div>
      <Row variant="head" cols={cols}>
        {children}
      </Row>
    </div>
  );
}
