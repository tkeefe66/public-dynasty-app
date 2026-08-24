"use client";

import { Fragment, useState } from "react";
import type { SideBetUpdateBody, SideBetView } from "@/lib/types";
import { fmtDateShort } from "@/lib/format-date";
import { formatCents } from "@/lib/money";
import { Section as Card, SectionTitle as CardHead } from "@/components/furniture/Section";
import { Panel } from "@/components/furniture/Panel";
import { Row } from "@/components/furniture/Row";
import { Name } from "@/components/furniture/Name";
import { CardList, EntryCard, Meta, MetaLine } from "@/components/furniture/EntryCard";
import { StateMessage } from "@/components/furniture/StateMessage";

/**
 * Furniture — the bets ledger.
 *
 * DESKTOP is a `Panel`: three `Row`s per bet (sides + stake, the bet itself as
 * one ellipsised prose row, then status and actions). A `Panel` is solid, so
 * every row draws its own `--rule` hairline.
 *
 * THE PHONE IS A CARD, one per bet, and the bet's own DESCRIPTION is the
 * card's name — it is the subject of the entry, which the desktop table can
 * only express by giving it a whole row of its own. The stake is the headline
 * figure; the two sides, the date and the status are facts under a single
 * hairline. Three stacked `Row`s on a phone drew two internal dividers per
 * bet at the same weight as the boundary between bets, which is what
 * `EntryCard` exists to stop: a card's edge IS the entry boundary.
 *
 * "Won by <name>" is PLAIN INK, never `--pos`. Colour may only carry what the
 * figure or the sort order already carries, and a name is not a signed value:
 * green on a winner's name would mean the same green means "positive money" in
 * one place and "this person" in another.
 */

/** The status fact, as it reads on a card: `Status Open` / `Won by Tom`. */
function StatusMeta({ bet }: { bet: SideBetView }) {
  if (bet.status === "settled") {
    const winner = bet.winner_owner_id === bet.side_a.user_id ? bet.side_a : bet.side_b;
    return <Meta label="Won by">{winner.owner_name}</Meta>;
  }
  if (bet.status === "push") return <Meta label="Status">Push</Meta>;
  if (bet.status === "void") return <Meta label="Status">Void</Meta>;
  return <Meta label="Status">Open</Meta>;
}

function StatusMark({ bet }: { bet: SideBetView }) {
  if (bet.status === "settled") {
    const winner = bet.winner_owner_id === bet.side_a.user_id ? bet.side_a : bet.side_b;
    // Plain ink: the name of a winner is an identity, not a signed figure.
    return (
      <span className="text-label uppercase tracking-[0.1em] text-ink">
        {winner.owner_name} won
      </span>
    );
  }
  if (bet.status === "push") {
    return <span className="text-label uppercase tracking-[0.1em]">Push</span>;
  }
  if (bet.status === "void") {
    return (
      <span className="text-label uppercase tracking-[0.1em] line-through">
        Void
      </span>
    );
  }
  return <span className="text-label uppercase tracking-[0.1em]">Open</span>;
}

function Actions({
  bet,
  onAction,
  on = "row",
}: {
  bet: SideBetView;
  onAction: (betId: string, body: SideBetUpdateBody) => Promise<void>;
  /** "card" gives every action a full 44px tap target on a phone. */
  on?: "row" | "card";
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const act = (body: SideBetUpdateBody) => async () => {
    setBusy(true);
    setError(null);
    try {
      await onAction(bet.id, body);
    } catch {
      setError("Couldn't update the bet.");
    } finally {
      setBusy(false);
    }
  };
  const card = on === "card";
  const btn =
    "text-label uppercase tracking-[0.1em] hover:text-ink disabled:text-rule" +
    // A phone action is a tap target, not a word: 44px minimum, and the
    // negative margin keeps the enlarged hit box from indenting the text.
    (card ? " inline-flex items-center min-h-tap px-2 -mx-2" : "");
  const wrap = card
    // `gap-y` is NOT optional: these children are `min-h-tap`, so four actions
    // on a narrow card wrap and the 44px hit boxes then sit flush against each
    // other with no separation. A wrapped row of adjacent tap targets is the
    // defect this gap exists to prevent.
    ? "flex flex-wrap items-center gap-x-5 gap-y-2"
    : "inline-flex items-center gap-3 justify-self-end";

  return (
    <span className={wrap}>
      {error && <span className="text-label uppercase tracking-[0.1em] text-neg-strong">{error}</span>}
      {bet.status !== "open" ? (
        <button type="button" className={btn} disabled={busy} onClick={act({ status: "open" })}>
          Reopen
        </button>
      ) : (
        <>
          <button
            type="button"
            className={btn}
            disabled={busy}
            onClick={act({ status: "settled", winner_owner_id: bet.side_a.user_id })}
          >
            {bet.side_a.owner_name} won
          </button>
          <button
            type="button"
            className={btn}
            disabled={busy}
            onClick={act({ status: "settled", winner_owner_id: bet.side_b.user_id })}
          >
            {bet.side_b.owner_name} won
          </button>
          <button type="button" className={btn} disabled={busy} onClick={act({ status: "push" })}>
            Push
          </button>
          <button type="button" className={btn} disabled={busy} onClick={act({ status: "void" })}>
            Void
          </button>
        </>
      )}
    </span>
  );
}

export function BetLedger({
  bets,
  onAction,
}: {
  bets: SideBetView[];
  onAction: (betId: string, body: SideBetUpdateBody) => Promise<void>;
}) {
  if (bets.length === 0) {
    return (
      <StateMessage
        kicker="No bets yet"
        headline="Every bet in the league, and who's paid up."
        body="Record one and it lands here with the stake, the terms, and a running net for both sides."
      />
    );
  }
  return (
    <Card>
      <CardHead title="Ledger" />

      {/* Desktop — three rules per bet. */}
      <Panel className="hidden min-[701px]:block">
        {bets.map((bet) => (
          <Fragment key={bet.id}>
            <Row cols="minmax(0,1fr) 84px">
              <span className="min-w-0 truncate">
                <span className="font-display font-bold tracking-[-0.02em] text-ink">
                  {bet.side_a.owner_name}
                </span>
                <span className="mx-1 text-label uppercase tracking-[0.1em]">vs</span>
                <span className="font-display font-bold tracking-[-0.02em] text-ink">
                  {bet.side_b.owner_name}
                </span>
                <span className="ml-2 text-label tabular">
                  {bet.season} · {bet.made_at}
                </span>
              </span>
              <span className="text-right font-semibold text-ink">
                {formatCents(bet.amount_cents)}
              </span>
            </Row>
            {/* Prose gets its own full-width row and ellipsises rather than
                reflowing onto the next entry; the full text stays available
                on hover. */}
            <Row>
              <span className="block truncate text-body" title={bet.description}>
                {bet.description}
              </span>
            </Row>
            <Row cols="auto minmax(0,1fr)">
              <StatusMark bet={bet} />
              <Actions bet={bet} onAction={onAction} />
            </Row>
          </Fragment>
        ))}
      </Panel>

      {/* Phone — one card per bet. The description leads because it is what
          the entry is ABOUT; on desktop it can only get a row of its own, and
          a phone has no room to spend a rule on it. It WRAPS here rather than
          truncating: there is no hover to recover a clipped bet on a phone. */}
      <div data-testid="bet-cards" className="min-[701px]:hidden">
        <CardList>
          {bets.map((bet) => (
            <EntryCard key={bet.id}>
              <div className="flex items-start gap-2.5">
                <span className="min-w-0 flex-1">
                  <Name>{bet.description}</Name>
                </span>
                <span className="shrink-0 grid justify-items-end">
                  <span className="font-mono text-name font-semibold tabular leading-tight text-ink">
                    {formatCents(bet.amount_cents)}
                  </span>
                  <span className="font-mono text-label uppercase tracking-[0.11em] text-dim">
                    At stake
                  </span>
                </span>
              </div>

              <MetaLine>
                <Meta>{`${bet.side_a.owner_name} vs ${bet.side_b.owner_name}`}</Meta>
                <Meta label="Season">{bet.season}</Meta>
                <Meta label="Made">{fmtDateShort(bet.made_at)}</Meta>
                <StatusMeta bet={bet} />
              </MetaLine>

              {/* No second hairline: `MetaLine`'s is the one rule a card gets,
                  and a divider between an entry's own children reads at the
                  weight that separates one entry from the next. */}
              <div className="mt-1">
                <Actions bet={bet} onAction={onAction} on="card" />
              </div>
            </EntryCard>
          ))}
        </CardList>
      </div>
    </Card>
  );
}
