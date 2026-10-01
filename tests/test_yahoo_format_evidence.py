import pytest


@pytest.mark.parametrize("settings", [
    {}, {"uses_roster_import":"maybe"}, {"is_keeper_league":"false","uses_roster_import":"0"},
    {"is_keeper_league":False}, {"uses_roster_import":1.0},
])
def test_incomplete_or_malformed_format_cannot_authorize(settings):
    from sleeper_dynasty.api.yahoo import _format_evidence
    assert not _format_evidence(settings)


def test_provider_integer_and_string_flags_are_evidence():
    from sleeper_dynasty.api.yahoo import _format_evidence
    assert _format_evidence({"uses_roster_import":"1"})
    assert _format_evidence({"uses_roster_import":0,"is_keeper_league":"0"})
