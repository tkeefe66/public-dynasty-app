"""Synthetic incident regression, including correct prose that must remain valid."""
import json
from pathlib import Path

import pytest

from sleeper_dynasty.llm.recap_packet import ArchivedPacket
from sleeper_dynasty.llm.recap_writer import require_scoring_claims


@pytest.fixture
def captured():
    return json.loads((Path(__file__).parent/'fixtures/recap_editorial_regression.json').read_text())


@pytest.mark.parametrize('claim', [
    'In 2025. On purpose.',
    'OwnerC: your tight end and your QB1 combine for fewer points than Sample Runner had by himself.',
    "OwnerH had the week's high scorer and the week's negative scorer on the same roster.",
    'If OwnerH wins, OwnerC is three games out of the cutoff after two weeks.',
    'The entire offensive contribution was 1.4 points combined.',
    'Three players all individually outscored what some full rosters managed.',
    'All totals below are optimized-lineup projections.',
    'OwnerB (2-0) hosts the struggling OwnerE (1-1).',
    'OwnerH hosts OwnerC.',
])
def test_incident_claims_override_an_approving_review(captured, claim):
    # Mutation: omit deterministic editorial validation from final publication guard.
    with pytest.raises(ValueError, match='editorial claim'):
        require_scoring_claims(claim, ArchivedPacket(captured['facts']))


def test_corrected_complete_article_passes(captured):
    # Mutation: treat a disclaimer about the cutoff as a conditional cutoff prediction.
    require_scoring_claims(captured['corrected'], ArchivedPacket(captured['facts']))


def test_complete_invalid_article_is_blocked(captured):
    # Mutation: check only synthetic sentences and let the complete synthetic article pass.
    with pytest.raises(ValueError, match='editorial claim'):
        require_scoring_claims(captured['original'], ArchivedPacket(captured['facts']))


def test_projection_language_requires_outlook_packet(captured):
    # Mutation: ban projection language even when a saved outlook exists.
    require_scoring_claims('All totals below are optimized-lineup projections.',
                           ArchivedPacket(captured['facts']), ArchivedPacket({'week': 3}))


@pytest.mark.parametrize('claim', [
    'In 2026. On purpose.',
    'Back in 2025. That was a different season.',
    "OwnerH posted the week's highest team score.",
    "OwnerB had the week's high scorer on his roster.",
    'If OwnerH wins, OwnerC falls two wins behind OwnerH. The cutoff also depends on other games.',
    'OwnerB faces OwnerE.',
    'A 50-point blowout.',
    'Sample Quarterback and Sample Tight End contributed 15 points combined.',
    'If OwnerH wins, the playoff cutoff still depends on other games.',
    'All totals below are actual Week 2 scores.',
    'OwnerC: your tight end and your QB1 combine for fewer points than Sample Leader had by himself. OwnerH won his game.',
])
def test_valid_distinctions_and_rounded_margin_are_allowed(captured, claim):
    # Mutation: ban all superlatives, season references, conditional records or rounded scores.
    require_scoring_claims(claim, ArchivedPacket(captured['facts']))
