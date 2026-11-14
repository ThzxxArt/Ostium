"""traffic day index and canonical rule-set format

Revision ID: d41f7a2c9b30
Revises: 8c9f85297917
Create Date: 2026-11-15 10:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "d41f7a2c9b30"
down_revision: str | None = "8c9f85297917"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("traffic_user_daily", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_traffic_user_daily_day"), ["day"], unique=False
        )
    # 0.1.1 stored the file extension as the format name.  sing-box expects
    # "binary" for an .srs local rule set; normalize existing rows so an
    # upgrade does not make a previously working profile fail validation.
    op.execute("UPDATE rule_sets SET format = 'binary' WHERE format = 'srs'")


def downgrade() -> None:
    with op.batch_alter_table("traffic_user_daily", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_traffic_user_daily_day"))
