import type { OwnerBetSummary } from "@/lib/types";
import { formatCents, formatSignedCents } from "@/lib/money";
import { Section as Card, SectionTitle as CardHead } from "@/components/furniture/Section";
import { Panel } from "@/components/furniture/Panel";
import { Row } from "@/components/furniture/Row";
import { Name } from "@/components/furniture/Name";
import { CardList, EntryCard, Meta, MetaLine } from "@/components/furniture/EntryCard";

/**
 * Furniture — the money standings, "who's up, who's down".
 *
 * Desktop is a `Panel` ledger, one rule per owner. THE PHONE IS A CARD, not a
 * narrower row: this used to wrap each owner onto three `Row`s inside one
 * `Panel`, and because a solid `Panel` makes every `Row` draw its own
 * `--rule` hairline, each owner was cut by two internal lines at exactly the
 * weight that separates one owner from the next — you could not see where an
 * entry ended. `EntryCard.prompt.md` names it: "a card's edge IS the entry
 * boundary."
 *
 * The headline is NET, because net is what the question in the heading asks.
 * It is the only signed figure here and the only one that takes colour — Won
 * and Lost are magnitudes whose direction is carried by their label, so
 * tinting them would be colour repeating a category rather than a sign. They
 * still RECONCILE with the headline (net = won − lost), which is why they are
 * the facts under it rather than the record.
 */

const GRID = "minmax(0,1fr) 64px 72px 72px 78px 78px";

function tone(cents: number) {
  return cents > 0 ? "text-pos-strong" : cents < 0 ? "text-neg-strong" : "text-dim";
}

/**
 * `Meta` tone for a magnitude (Won / Lost / Open). Never coloured — the label
 * carries the direction — but zero is still `dim` rather than untoned, because
 * untoned renders full-weight ink and reads as a result.
 */
function magnitudeTone(cents: number): "dim" | undefined {
  return cents === 0 ? "dim" : undefined;
}

export function BetLeaderboard({ rows }: { rows: OwnerBetSummary[] }) {
  if (rows.length === 0) return null;
  return (
    <Card>
      <CardHead title="Who's up, who's down" />

      {/* Desktop — one rule per owner. */}
      <Panel className="hidden min-[701px]:block">
        <Row variant="head" cols={GRID}>
          <div>Owner</div>
          <div className="text-right">W-L-P</div>
          <div className="text-right">Won</div>
          <div className="text-right">Lost</div>
          <div className="text-right">Net</div>
          <div className="text-right">At stake</div>
        </Row>
        {rows.map((r) => (
          <Row key={r.owner.user_id} cols={GRID}>
            <div className="min-w-0 truncate font-display font-bold tracking-[-0.02em] text-ink">
              {r.owner.owner_name}
            </div>
            <div className="text-right">
              {r.won}-{r.lost}-{r.pushed}
            </div>
            <div className="text-right">{formatCents(r.cents_won)}</div>
            <div className="text-right">{formatCents(r.cents_lost)}</div>
            <div className={`text-right font-semibold ${tone(r.net_cents)}`}>
              {formatSignedCents(r.net_cents)}
            </div>
            <div className="text-right">{formatCents(r.cents_at_stake)}</div>
          </Row>
        ))}
      </Panel>

      {/* Phone — one card per owner. Every desktop column survives: the record
          is a fact rather than a dropped column, and "At stake" is labelled
          "Open" here because on a card the word has room to say what it means
          without a header row above it. */}
      <div data-testid="bet-leader-cards" className="min-[701px]:hidden">
        <CardList>
          {rows.map((r) => (
            <EntryCard key={r.owner.user_id}>
              <div className="flex items-center gap-2.5">
                <span className="min-w-0 flex-1">
                  <Name title={r.owner.owner_name}>{r.owner.owner_name}</Name>
                </span>
                <span className="shrink-0 grid justify-items-end">
                  <span
                    className={`font-mono text-name font-semibold tabular leading-tight ${tone(
                      r.net_cents,
                    )}`}
                  >
                    {formatSignedCents(r.net_cents)}
                  </span>
                  <span className="font-mono text-label uppercase tracking-[0.11em] text-dim">
                    Net
                  </span>
                </span>
              </div>

              <MetaLine>
                <Meta label="Won" tone={magnitudeTone(r.cents_won)}>
                  {formatCents(r.cents_won)}
                </Meta>
                <Meta label="Lost" tone={magnitudeTone(r.cents_lost)}>
                  {formatCents(r.cents_lost)}
                </Meta>
                <Meta label="Open" tone={magnitudeTone(r.cents_at_stake)}>
                  {formatCents(r.cents_at_stake)}
                </Meta>
              </MetaLine>
            </EntryCard>
          ))}
        </CardList>
      </div>
    </Card>
  );
}
