"""Adopt text reconciliation for existing policy documents."""
import json
import time
import uuid

import sqlalchemy as sa
from alembic import op

revision = '0022_text_reconciliation'
down_revision = '0021_recap_monitor'
branch_labels = None
depends_on = None


def upgrade():
    # Older full-document saves materialized the old false default. This
    # one-time adoption leaves feature modes, pauses and every limit intact.
    # Admission still requires the existing series activation boundary; no
    # historical candidate, episode or operation is authorized here.
    conn = op.get_bind()
    control = sa.table('generation_control', sa.column('id', sa.String))
    # Use the same mutation lock as owner policy edits and job admission.
    conn.execute(sa.select(control.c.id).where(control.c.id == 'global').with_for_update()).all()
    policies = sa.table('generation_policies', sa.column('scope', sa.String),
        sa.column('revision', sa.Integer), sa.column('value_json', sa.String))
    audits = sa.table('generation_audit', sa.column('id', sa.String),
        sa.column('actor_id', sa.String), sa.column('action', sa.String),
        sa.column('target', sa.String), sa.column('reason', sa.String),
        sa.column('before_json', sa.String), sa.column('after_json', sa.String),
        sa.column('created_at', sa.BigInteger))
    for row in conn.execute(sa.select(policies)).mappings().all():
        before = json.loads(row['value_json'])
        if before.get('recap_text_reconciliation') is not False:
            continue
        after = {key: value for key, value in before.items() if key != 'recap_text_reconciliation'}
        revision = row['revision'] + 1
        conn.execute(policies.update().where(policies.c.scope == row['scope']).values(
            revision=revision, value_json=json.dumps(after, sort_keys=True, separators=(',', ':'))))
        conn.execute(audits.insert().values(id=uuid.uuid4().hex,
            actor_id='migration:0022_text_reconciliation', action='text_reconciliation_default_adopted',
            target=row['scope'], reason='Adopt text correction evidence without changing generation authorization or spending limits',
            before_json=json.dumps({'revision': row['revision'], 'value': before}, sort_keys=True),
            after_json=json.dumps({'revision': revision, 'value': after}, sort_keys=True),
            created_at=int(time.time())))


def downgrade():
    # Retain owner policy edits and immutable adoption evidence on rollback.
    # Older application code uses its false default when this key is absent.
    pass
