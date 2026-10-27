"""Successful polling is not progress toward a published recap."""
from types import SimpleNamespace

from app.services.recap_monitor.evidence import workflow_evidence


def job(ident, **kwargs):
    return SimpleNamespace(id=ident, kind='analyst_refresh', state='succeeded',
        generation=1, calls=0, updated_at=100, progress_json='{}', **kwargs)


def test_completed_refresh_churn_does_not_reset_stall_detection():
    assert workflow_evidence(job('first'), None, 100)['progress'] == workflow_evidence(job('second'), None, 200)['progress']


def test_episode_hold_is_actionable_even_when_refresh_succeeded():
    episode = SimpleNamespace(episode_id='episode', lifecycle='correction',
        hold='recap_dependency_changed', facts_digest='facts', eligible_at=50,
        stable_since=1)
    result = workflow_evidence(job('import'), episode, 100)
    assert result['status'] == 'help'
    assert result['reason'] == 'recap_dependency_changed'
    assert not result['recoverable']
    assert 'earlier' in result['action']


def test_legitimate_stability_wait_has_next_useful_check():
    episode = SimpleNamespace(episode_id='episode', lifecycle='held',
        hold='facts_unstable', facts_digest='facts', eligible_at=50,
        stable_since=100)
    result = workflow_evidence(job('import'), episode, 200)
    assert result['status'] == 'waiting' and result['gate'] == 3700


def test_generation_stage_changes_are_real_progress():
    first = job('paid')
    first.kind, first.state = 'generation', 'running'
    before = workflow_evidence(first, None, 100)['progress']
    first.calls = 1
    assert workflow_evidence(first, None, 200)['progress'] != before
