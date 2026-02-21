import datetime
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Ingest payload (mirrors OSS get_scan_payload output)
# ---------------------------------------------------------------------------

class FieldPayload(BaseModel):
    id: int | None = None
    name: str
    type: str | None = None
    uri: str


class MetricPayload(BaseModel):
    id: int | None = None
    metric_name: str
    metric_value: str | None = None
    uri: str
    ts: str | None = None


class TablePayload(BaseModel):
    id: int | None = None
    name: str
    uri: str
    db_name: str | None = None
    schema_name: str | None = None
    fields: list[FieldPayload] = []
    metrics: list[MetricPayload] = []


class FilePayload(BaseModel):
    id: int | None = None
    name: str
    uri: str
    filetype: str | None = None
    file_encoding: str | None = None
    fields: list[FieldPayload] = []


class SourcePayload(BaseModel):
    id: int | None = None
    name: str
    type: str | None = None
    uri: str
    tables: list[TablePayload] = []
    files: list[FilePayload] = []


class IngestRequest(BaseModel):
    cli_version: str | None = None
    sources: list[SourcePayload] = []


class IngestResponse(BaseModel):
    ingest_event_id: int
    sources_processed: int
    tables_processed: int
    anomalies_detected: int


# ---------------------------------------------------------------------------
# API Token management
# ---------------------------------------------------------------------------

class TokenCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    expires_at: datetime.datetime | None = None


class TokenResponse(BaseModel):
    id: int
    name: str
    token_prefix: str
    created_at: datetime.datetime
    last_used_at: datetime.datetime | None
    expires_at: datetime.datetime | None
    is_active: bool

    model_config = {"from_attributes": True}


class TokenCreated(TokenResponse):
    plain_token: str


# ---------------------------------------------------------------------------
# Anomaly
# ---------------------------------------------------------------------------

class AnomalyResponse(BaseModel):
    id: int
    metric_uri: str
    metric_name: str
    table_uri: str
    anomaly_ts: datetime.datetime | None
    observed_value: float | None
    z_score: float | None
    algorithm: str
    is_acknowledged: bool
    alert_sent: bool
    created_at: datetime.datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

class SourceResponse(BaseModel):
    id: int
    name: str
    type: str | None
    uri: str
    last_seen_at: datetime.datetime

    model_config = {"from_attributes": True}
