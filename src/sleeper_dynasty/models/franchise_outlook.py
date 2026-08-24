"""Facts packet for the LLM franchise-outlook blurb (mirrors gm_rating_blurb)."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from sleeper_dynasty.models._signature import signature_hash

# A draft-capital net inside this many picks of league-average is the same as
# league-average. Below it the *status* is "neutral" too, and both fields are
# dropped rather than sent: the prompt says "use ONLY these facts", so a fact
# that carries no information still gets used. The deployed blurb reached for
# "that neutral draft capital" exactly because it was there to reach for.
DRAFT_CAPITAL_EPSILON = 0.5


@dataclass
class FranchiseFacts:
    user_id: str
    owner_name: str
    team_name: str | None
    # dynasty | keeper | redraft. Stated so the writer stops importing rules
    # from other fantasy formats it has read about — this league has no salary
    # cap, no contracts and no auction budget, and prose invented all three.
    league_format: str
    window: str
    # Share of this owner's roster VALUE held by players 25-and-under (0..1).
    # Replaces the old `trajectory` prose + `overall_avg_age`, both of which
    # were mean roster age — the metric the v2 rating dropped because a mean
    # measures bench filler. The grade and the prose now run on one theory of
    # "young". None when the signal is unavailable (then it is not sent).
    young_core_share: float | None
    roster_rank: int | None
    roster_of: int | None
    young_core: list[str]
    aging_risks: list[str]
    draft_capital_status: str
    draft_capital_net: float
    top_need: str | None
    signature_trade: str | None

    def to_dict(self) -> dict:
        """The packet as sent — pruned of anything that says nothing.

        Identity (`user_id`, `owner_name`) is never pruned; everything else is
        dropped when it is None, empty, or informationally neutral.
        """
        d = asdict(self)

        net = d.get("draft_capital_net")
        status = d.get("draft_capital_status")
        if status == "neutral" or abs(float(net or 0.0)) < DRAFT_CAPITAL_EPSILON:
            d.pop("draft_capital_status", None)
            d.pop("draft_capital_net", None)

        keep_always = {"user_id", "owner_name"}
        return {
            k: v for k, v in d.items()
            # `is None` and emptiness, not falsiness: young_core_share 0.0 and
            # a negative draft_capital_net are both real readings.
            if k in keep_always or (v is not None and v != "" and v != [])
        }


def franchise_facts_hash(facts: FranchiseFacts) -> str:
    """Stable 16-char hash of the facts packet (used for incremental skip).

    Coarsened so the outlook regenerates on material change (window shift,
    roster-rank move, draft-capital band, young-core-share band) but not on
    per-refresh value drift. Hashes the PRUNED packet, so a signal going
    neutral is itself a material change. See _signature.py.
    """
    return signature_hash(facts.to_dict())
