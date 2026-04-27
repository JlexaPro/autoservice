"""Baseline revision for existing autoservice_crm_web schema.

Revision ID: 0001_baseline_existing_schema
Revises:
Create Date: 2026-04-27
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "0001_baseline_existing_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Baseline only. Existing deployments should use: alembic stamp head
    pass


def downgrade() -> None:
    pass
