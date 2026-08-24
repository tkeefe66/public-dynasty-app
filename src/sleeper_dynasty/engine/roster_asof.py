"""Reconstruct an owner's roster as it stood on a given date.

Replays a transaction log against a seed roster, applying adds/drops in
timestamp order up to (and including) a cutoff date. Used to recover the
roster a draft-day owner actually held, for grading draft needs against.

Pure. No I/O, no client — transactions in, roster out. The seed is NOT
``get_rosters``: that returns Sleeper's LIVE state, which for a rolled-over
dynasty league may already reflect offseason moves this reconstruction would
then apply a second time. Building the seed is the caller's job.
"""

from __future__ import annotations

from datetime import datetime, timezone


def _tx_timestamp(tx: dict) -> datetime | None:
    """Epoch-millis ``status_updated``/``created`` -> aware datetime, else
    None. A transaction with no usable timestamp is skipped by the caller,
    never guessed at."""
    raw = tx.get("status_updated")
    if raw is None:
        raw = tx.get("created")
    if raw is None:
        return None
    try:
        return datetime.fromtimestamp(int(raw) / 1000.0, tz=timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def roster_asof(
    seed: dict[str, set[str]],
    transactions: list[dict],
    roster_to_user: dict[int, str],
    as_of: datetime,
) -> dict[str, set[str]]:
    """``owner_user_id -> {player_id}`` as of ``as_of``.

    Sleeper's ``adds``/``drops`` map ``player_id -> roster_id`` — the roster
    id is the VALUE, not the key. Roster ids are not stable across a league
    chain, so every mutation is resolved through ``roster_to_user`` to an
    owner id before being applied; nothing here is keyed by roster id.

    Transactions are applied in ``status_updated``/``created`` order
    (out-of-order input yields the same result as sorted input), restricted
    to those on or before ``as_of``. A transaction with no usable timestamp
    is dropped rather than guessed at.

    Does not mutate ``seed``.
    """
    rosters: dict[str, set[str]] = {
        owner: set(players) for owner, players in seed.items()
    }

    dated: list[tuple[datetime, dict]] = []
    for tx in transactions:
        ts = _tx_timestamp(tx)
        if ts is None or ts > as_of:
            continue
        dated.append((ts, tx))
    dated.sort(key=lambda pair: pair[0])

    for _, tx in dated:
        drops = tx.get("drops") or {}
        for player_id, roster_id in drops.items():
            owner = roster_to_user.get(roster_id)
            if owner is None:
                continue
            rosters.setdefault(owner, set()).discard(player_id)

        adds = tx.get("adds") or {}
        for player_id, roster_id in adds.items():
            owner = roster_to_user.get(roster_id)
            if owner is None:
                continue
            rosters.setdefault(owner, set()).add(player_id)

    return rosters
