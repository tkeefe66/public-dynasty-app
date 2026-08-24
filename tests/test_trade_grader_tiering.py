from sleeper_dynasty.engine.trade_grader import _ktc_value
from sleeper_dynasty.models.player import KTCValue
from sleeper_dynasty.models.trade import PickAsset


def _kv(sf):
    return KTCValue(name="p", normalized_name="p", position="PICK",
                    superflex_value=sf, one_qb_value=sf)


def _future_pick(owner_uid):
    return PickAsset(season=2027, round=1, original_owner_user_id=owner_uid,
                     drafted_player_id=None, drafted_player_name=None)


def test_snapshot_pick_tiered_by_original_owner():
    round_avg = {(2027, 1): _kv(6500)}
    tiered = {(2027, 1, "early"): _kv(9000), (2027, 1, "late"): _kv(4000)}
    tiers = {"weak": "early", "strong": "late"}
    early = _ktc_value(_future_pick("weak"), {}, "superflex", round_avg,
                       tier_by_user=tiers, tiered_values=tiered)
    late = _ktc_value(_future_pick("strong"), {}, "superflex", round_avg,
                      tier_by_user=tiers, tiered_values=tiered)
    assert early == 9000.0 and late == 4000.0


def test_at_trade_path_stays_round_average():
    round_avg = {(2027, 1): _kv(6500)}
    tiered = {(2027, 1, "early"): _kv(9000)}
    v = _ktc_value(_future_pick("weak"), {}, "superflex", round_avg,
                   ignore_drafted_player=True,
                   tier_by_user={"weak": "early"}, tiered_values=tiered)
    assert v == 6500.0
