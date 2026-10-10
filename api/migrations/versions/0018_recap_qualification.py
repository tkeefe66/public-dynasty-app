"""Immutable rollout, context and recovery evidence. Never activates media."""
from alembic import op
import sqlalchemy as sa

revision = '0018_recap_qualification'
down_revision = '0017_recap_publication'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('recap_stages') as batch:
        batch.add_column(sa.Column('execution_revision', sa.Integer(), nullable=False, server_default='1'))
        batch.drop_constraint('uq_recap_stage', type_='unique')
        batch.create_unique_constraint('uq_recap_stage', ['episode_id','revision','execution_revision','kind','chunk'])
    op.add_column('recap_publication_approvals', sa.Column('authorization_kind', sa.String(), nullable=False, server_default='manual'))
    op.add_column('recap_publication_approvals', sa.Column('authorization_id', sa.String(), nullable=False, server_default=''))
    tables = {
        'recap_calibrations': [('id','s'),('series_id','s'),('season','i'),('config_json','s'),('metadata_json','s'),
            ('rate_json','s'),('versions_json','s'),('evidence_json','s'),('actor_id','s'),('created_at','n')],
        'recap_qualification_reviews': [('id','s'),('episode_id','s'),('series_id','s'),('season','i'),('calibration_id','s'),
            ('approval_id','s'),('binding_json','s'),('evidence_json','s'),('actor_id','s'),('passed','b'),('created_at','n')],
        'recap_standing_authorizations': [('id','s'),('series_id','s'),('season','i'),('calibration_id','s'),
            ('review_ids_json','s'),('actor_id','s'),('policy','s'),('created_at','n')],
        'recap_dependencies': [('id','s'),('episode_id','s'),('prior_episode_id','s'),('observation_id','s'),('facts_digest','s')],
        'recap_recoveries': [('id','s'),('episode_id','s'),('stage_id','s'),('action','s'),('before_json','s'),
            ('actor_id','s'),('reason','s'),('created_at','n')],
        'recap_recovery_requests': [('id','s'),('attempt_id','s'),('worker_id','s'),('actor_id','s'),('identity_json','s'),
            ('request_digest','s'),('epoch','s'),('state','s'),('generation','i'),('lease_until','n'),('error','s'),('reason','s'),('created_at','n')],
        'recap_attention': [('key','s'),('episode_id','s'),('state','s'),('reason','s'),('created_at','n')],
    }
    types = {'s':sa.String, 'i':sa.Integer, 'n':sa.BigInteger, 'b':sa.Boolean}
    for name, fields in tables.items():
        constraints = [sa.UniqueConstraint('episode_id','prior_episode_id','observation_id',name='uq_recap_dependency')] if name == 'recap_dependencies' else []
        op.create_table(name, *[sa.Column(key, types[kind](), primary_key=index == 0, nullable=False)
            for index,(key,kind) in enumerate(fields)], *constraints)
        for key, _ in fields:
            if key in ('episode_id','prior_episode_id','series_id','attempt_id'):
                op.create_index('ix_'+name+'_'+key, name, [key])


def downgrade():
    raise RuntimeError('Calibration, recovery and standing authorization evidence requires explicit archival review')
