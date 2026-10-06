"""add mentioned_clients to reports

Revision ID: c3d5f0a12b04
Revises: b2c4e8f91a03
Create Date: 2026-10-06 02:10:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c3d5f0a12b04"
down_revision: Union[str, Sequence[str], None] = "b2c4e8f91a03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "reports",
        sa.Column(
            "mentioned_clients",
            postgresql.ARRAY(sa.Text()),
            server_default="{}",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("reports", "mentioned_clients")
