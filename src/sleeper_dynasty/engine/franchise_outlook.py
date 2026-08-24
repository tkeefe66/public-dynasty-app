"""Build the franchise-outlook facts packet from a serialized dynasty outlook."""

from __future__ import annotations

from sleeper_dynasty.models.franchise_outlook import FranchiseFacts

# The persona asks for the strongest ONE OR TWO signals. Handing it eight aging
# risks is handing it a list to recite, and it recited one — naming every
# veteran on the roster instead of the two that matter. Three leaves room to
# pick without room to inventory.
MAX_LISTED = 3


def _top(
    players: list[dict],
    value_by_player: dict[str, float] | None,
    *,
    oldest_first: bool,
) -> list[str]:
    """The ``MAX_LISTED`` players that most deserve naming, by market value.

    Value is the right key: the aging risk worth a sentence is the one you hold
    the most value in, and so is the young piece. When no value map is threaded
    in (the CLI outlook path, and any caller predating this argument) the
    fallback is **age** — the only other field ``_player_lite`` carries, and
    still defensible in each direction: the oldest players are the most acute
    risks, the youngest the longest-dated core. Position and list order are the
    only other candidates, and list order is roster iteration order, which is
    arbitrary. Ties break on name so the packet is stable across refreshes and
    does not churn the skip hash.
    """
    def key(p: dict):
        age = p.get("age")
        # Missing age sorts last in both directions rather than reading as 0.
        age_key = -age if oldest_first else age
        if age is None:
            age_key = float("inf")
        value = float((value_by_player or {}).get(p.get("player_id"), 0.0) or 0.0)
        return (-value, age_key, p.get("full_name") or "")

    return [p["full_name"] for p in sorted(players, key=key)[:MAX_LISTED]]


def build_franchise_facts(
    *,
    user_id: str,
    owner_name: str,
    team_name: str | None,
    outlook: dict,
    roster_rank: dict | None,
    signature_trade: str | None,
    window: str = "",
    league_format: str = "dynasty",
    young_core_share: float | None = None,
    value_by_player: dict[str, float] | None = None,
) -> FranchiseFacts:
    """Assemble FranchiseFacts from the serialized outlook dict (outlook_to_dict).

    Note what is *not* read off the outlook: ``trajectory``, ``overall_avg_age``
    and — since the Assets-led redesign — ``window``.

    ``window`` is a PARAMETER, not a blob read, and that is load-bearing. The
    stage is now derived from the Franchise Rating (gm_rating.rating_to_stage),
    the redesign shipped without a SCHEMA_VERSION bump, and a pre-feature blob
    still carries a RETIRED stage string ("Peaking"). Reading it here would
    feed a word the validator's _VOCABULARY has just dropped into a packet the
    validator then checks. Pass "" for an unrated owner: FranchiseFacts.to_dict
    prunes it, so the writer is handed no stage rather than an empty one.

    ``trajectory`` and ``overall_avg_age`` are both mean roster age, which the
    v2 rating dropped because a mean measures bench filler rather than the
    core. Sending it produced prose that called a roster "trending downward" in
    the same sentence as its "legitimate young core". ``young_core_share`` —
    the value-weighted signal the grade actually scores — is threaded in
    instead.
    """
    ap = outlook.get("age_profile", {})
    dc = outlook.get("draft_capital", {})
    needs = outlook.get("draft_needs", []) or []
    # Most-urgent need first ("immediate" before "developing").
    needs_sorted = sorted(
        needs, key=lambda n: 0 if n.get("urgency") == "immediate" else 1)
    top_need = (
        f"{needs_sorted[0]['position']} ({needs_sorted[0]['urgency']})"
        if needs_sorted else None
    )
    return FranchiseFacts(
        user_id=user_id,
        owner_name=owner_name,
        team_name=team_name,
        league_format=league_format,
        window=window,
        young_core_share=(
            None if young_core_share is None else round(float(young_core_share), 3)),
        roster_rank=(roster_rank or {}).get("rank"),
        roster_of=(roster_rank or {}).get("of"),
        young_core=_top(ap.get("core_young", []) or [], value_by_player,
                        oldest_first=False),
        aging_risks=_top(ap.get("aging_risks", []) or [], value_by_player,
                         oldest_first=True),
        draft_capital_status=dc.get("status", ""),
        draft_capital_net=float(dc.get("net_vs_average", 0.0) or 0.0),
        top_need=top_need,
        signature_trade=signature_trade,
    )
