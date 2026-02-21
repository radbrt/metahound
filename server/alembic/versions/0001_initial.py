"""Initial schema

Revision ID: 0001
Revises:
Create Date: 2026-02-20
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "orgs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False, unique=True),
        sa.Column("alert_email", sa.String(255)),
        sa.Column("slack_webhook_url", sa.Text),
        sa.Column("alerts_enabled", sa.Boolean, default=False),
    )

    op.create_table(
        "api_tokens",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("org_id", sa.Integer, sa.ForeignKey("orgs.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("token_hash", sa.String(255), nullable=False),
        sa.Column("token_prefix", sa.String(8), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime),
        sa.Column("last_used_at", sa.DateTime),
        sa.Column("expires_at", sa.DateTime),
        sa.Column("is_active", sa.Boolean, default=True),
    )

    op.create_table(
        "ingest_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("org_id", sa.Integer, sa.ForeignKey("orgs.id"), nullable=False),
        sa.Column("received_at", sa.DateTime),
        sa.Column("cli_version", sa.String(50)),
        sa.Column("source_count", sa.Integer, default=0),
    )

    op.create_table(
        "cloud_sources",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("org_id", sa.Integer, sa.ForeignKey("orgs.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("type", sa.String(50)),
        sa.Column("uri", sa.String(1024), nullable=False),
        sa.Column("last_seen_at", sa.DateTime),
        sa.UniqueConstraint("org_id", "uri", name="uq_cloud_sources_org_uri"),
    )

    op.create_table(
        "cloud_tables",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("source_id", sa.Integer, sa.ForeignKey("cloud_sources.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("uri", sa.String(1024), nullable=False),
        sa.Column("db_name", sa.String(255)),
        sa.Column("schema_name", sa.String(255)),
        sa.UniqueConstraint("source_id", "uri", name="uq_cloud_tables_source_uri"),
    )

    op.create_table(
        "cloud_files",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("source_id", sa.Integer, sa.ForeignKey("cloud_sources.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("uri", sa.String(1024), nullable=False),
        sa.Column("filetype", sa.String(50)),
        sa.Column("file_encoding", sa.String(50)),
        sa.UniqueConstraint("source_id", "uri", name="uq_cloud_files_source_uri"),
    )

    op.create_table(
        "cloud_fields",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("type", sa.String(100)),
        sa.Column("uri", sa.String(1024), nullable=False),
        sa.Column("table_id", sa.Integer, sa.ForeignKey("cloud_tables.id")),
        sa.Column("file_id", sa.Integer, sa.ForeignKey("cloud_files.id")),
    )

    op.create_table(
        "cloud_table_metrics",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("table_id", sa.Integer, sa.ForeignKey("cloud_tables.id"), nullable=False),
        sa.Column("ingest_event_id", sa.Integer, sa.ForeignKey("ingest_events.id")),
        sa.Column("metric_name", sa.String(255), nullable=False),
        sa.Column("metric_value", sa.Float),
        sa.Column("uri", sa.String(1024), nullable=False),
        sa.Column("ts", sa.DateTime),
    )
    op.create_index("ix_cloud_table_metrics_uri_ts", "cloud_table_metrics", ["uri", "ts"])
    op.create_index("ix_cloud_table_metrics_table_id", "cloud_table_metrics", ["table_id"])

    op.create_table(
        "anomalies",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("org_id", sa.Integer, sa.ForeignKey("orgs.id"), nullable=False),
        sa.Column("ingest_event_id", sa.Integer, sa.ForeignKey("ingest_events.id")),
        sa.Column("metric_uri", sa.String(1024), nullable=False),
        sa.Column("metric_name", sa.String(255), nullable=False),
        sa.Column("table_uri", sa.String(1024), nullable=False),
        sa.Column("anomaly_ts", sa.DateTime),
        sa.Column("observed_value", sa.Float),
        sa.Column("z_score", sa.Float),
        sa.Column("algorithm", sa.String(50), default="zscore"),
        sa.Column("is_acknowledged", sa.Boolean, default=False),
        sa.Column("alert_sent", sa.Boolean, default=False),
        sa.Column("created_at", sa.DateTime),
    )


def downgrade() -> None:
    op.drop_table("anomalies")
    op.drop_index("ix_cloud_table_metrics_table_id", "cloud_table_metrics")
    op.drop_index("ix_cloud_table_metrics_uri_ts", "cloud_table_metrics")
    op.drop_table("cloud_table_metrics")
    op.drop_table("cloud_fields")
    op.drop_table("cloud_files")
    op.drop_table("cloud_tables")
    op.drop_table("cloud_sources")
    op.drop_table("ingest_events")
    op.drop_table("api_tokens")
    op.drop_table("orgs")
