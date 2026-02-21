import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Org(Base):
    __tablename__ = "orgs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    alert_email: Mapped[str | None] = mapped_column(String(255))
    slack_webhook_url: Mapped[str | None] = mapped_column(Text)
    alerts_enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    api_tokens: Mapped[list["ApiToken"]] = relationship(back_populates="org", cascade="all, delete-orphan")
    ingest_events: Mapped[list["IngestEvent"]] = relationship(back_populates="org", cascade="all, delete-orphan")
    cloud_sources: Mapped[list["CloudSource"]] = relationship(back_populates="org", cascade="all, delete-orphan")
    anomalies: Mapped[list["Anomaly"]] = relationship(back_populates="org", cascade="all, delete-orphan")


class ApiToken(Base):
    __tablename__ = "api_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    token_prefix: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)
    last_used_at: Mapped[datetime.datetime | None] = mapped_column(DateTime)
    expires_at: Mapped[datetime.datetime | None] = mapped_column(DateTime)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    org: Mapped["Org"] = relationship(back_populates="api_tokens")


class IngestEvent(Base):
    __tablename__ = "ingest_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"), nullable=False)
    received_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)
    cli_version: Mapped[str | None] = mapped_column(String(50))
    source_count: Mapped[int] = mapped_column(Integer, default=0)

    org: Mapped["Org"] = relationship(back_populates="ingest_events")
    cloud_table_metrics: Mapped[list["CloudTableMetric"]] = relationship(back_populates="ingest_event")
    anomalies: Mapped[list["Anomaly"]] = relationship(back_populates="ingest_event")


class CloudSource(Base):
    __tablename__ = "cloud_sources"
    __table_args__ = (
        Index("ix_cloud_sources_org_uri", "org_id", "uri", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(50))
    uri: Mapped[str] = mapped_column(String(1024), nullable=False)
    last_seen_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)

    org: Mapped["Org"] = relationship(back_populates="cloud_sources")
    cloud_tables: Mapped[list["CloudTable"]] = relationship(back_populates="source", cascade="all, delete-orphan")
    cloud_files: Mapped[list["CloudFile"]] = relationship(back_populates="source", cascade="all, delete-orphan")


class CloudTable(Base):
    __tablename__ = "cloud_tables"
    __table_args__ = (
        Index("ix_cloud_tables_source_uri", "source_id", "uri", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("cloud_sources.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    uri: Mapped[str] = mapped_column(String(1024), nullable=False)
    db_name: Mapped[str | None] = mapped_column(String(255))
    schema_name: Mapped[str | None] = mapped_column(String(255))

    source: Mapped["CloudSource"] = relationship(back_populates="cloud_tables")
    cloud_fields: Mapped[list["CloudField"]] = relationship(
        back_populates="table",
        primaryjoin="CloudField.table_id == CloudTable.id",
        cascade="all, delete-orphan",
    )
    cloud_table_metrics: Mapped[list["CloudTableMetric"]] = relationship(back_populates="table", cascade="all, delete-orphan")


class CloudFile(Base):
    __tablename__ = "cloud_files"
    __table_args__ = (
        Index("ix_cloud_files_source_uri", "source_id", "uri", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("cloud_sources.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    uri: Mapped[str] = mapped_column(String(1024), nullable=False)
    filetype: Mapped[str | None] = mapped_column(String(50))
    file_encoding: Mapped[str | None] = mapped_column(String(50))

    source: Mapped["CloudSource"] = relationship(back_populates="cloud_files")
    cloud_fields: Mapped[list["CloudField"]] = relationship(
        back_populates="file",
        primaryjoin="CloudField.file_id == CloudFile.id",
        cascade="all, delete-orphan",
    )


class CloudField(Base):
    __tablename__ = "cloud_fields"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str | None] = mapped_column(String(100))
    uri: Mapped[str] = mapped_column(String(1024), nullable=False)
    table_id: Mapped[int | None] = mapped_column(ForeignKey("cloud_tables.id"))
    file_id: Mapped[int | None] = mapped_column(ForeignKey("cloud_files.id"))

    table: Mapped["CloudTable | None"] = relationship(back_populates="cloud_fields", primaryjoin="CloudField.table_id == CloudTable.id", foreign_keys=[table_id])
    file: Mapped["CloudFile | None"] = relationship(back_populates="cloud_fields", primaryjoin="CloudField.file_id == CloudFile.id", foreign_keys=[file_id])


class CloudTableMetric(Base):
    __tablename__ = "cloud_table_metrics"
    __table_args__ = (
        Index("ix_cloud_table_metrics_uri_ts", "uri", "ts"),
        Index("ix_cloud_table_metrics_table_id", "table_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    table_id: Mapped[int] = mapped_column(ForeignKey("cloud_tables.id"), nullable=False)
    ingest_event_id: Mapped[int | None] = mapped_column(ForeignKey("ingest_events.id"))
    metric_name: Mapped[str] = mapped_column(String(255), nullable=False)
    metric_value: Mapped[float | None] = mapped_column(Float)
    uri: Mapped[str] = mapped_column(String(1024), nullable=False)
    ts: Mapped[datetime.datetime | None] = mapped_column(DateTime)

    table: Mapped["CloudTable"] = relationship(back_populates="cloud_table_metrics")
    ingest_event: Mapped["IngestEvent | None"] = relationship(back_populates="cloud_table_metrics")


class Anomaly(Base):
    __tablename__ = "anomalies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"), nullable=False)
    ingest_event_id: Mapped[int | None] = mapped_column(ForeignKey("ingest_events.id"))
    metric_uri: Mapped[str] = mapped_column(String(1024), nullable=False)
    metric_name: Mapped[str] = mapped_column(String(255), nullable=False)
    table_uri: Mapped[str] = mapped_column(String(1024), nullable=False)
    anomaly_ts: Mapped[datetime.datetime | None] = mapped_column(DateTime)
    observed_value: Mapped[float | None] = mapped_column(Float)
    z_score: Mapped[float | None] = mapped_column(Float)
    algorithm: Mapped[str] = mapped_column(String(50), default="zscore")
    is_acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    alert_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)

    org: Mapped["Org"] = relationship(back_populates="anomalies")
    ingest_event: Mapped["IngestEvent | None"] = relationship(back_populates="anomalies")
