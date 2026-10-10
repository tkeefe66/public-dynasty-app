"""Private object recovery pins, deletion claims and restore evidence."""
from alembic import op
import sqlalchemy as sa

revision = '0019_recap_retention'
down_revision = '0018_recap_qualification'
branch_labels = None
depends_on = None


def upgrade():
    for name, fields in {
        'recap_backup_points': [('run_id','s'),('state','s'),('objects_json','s'),('authority_json','s'),('created_at','n'),('expires_at','n')],
        'recap_object_deletions': [('storage_key','s'),('asset_json','s'),('state','s'),('claimed_at','n')],
        'recap_restore_reports': [('epoch','s'),('digest','s'),('report_json','s'),('created_at','n')],
    }.items():
        op.create_table(name, *[sa.Column(key, sa.String() if kind == 's' else sa.BigInteger(),
            primary_key=i == 0, nullable=False) for i,(key,kind) in enumerate(fields)])


def downgrade():
    raise RuntimeError('Recovery pins and restore authority evidence require explicit archival review')
