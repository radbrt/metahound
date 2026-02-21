"""
Upsert catalog data from a push payload into the cloud schema.
"""
import datetime

from sqlalchemy.orm import Session

from app.models import (
    CloudField,
    CloudFile,
    CloudSource,
    CloudTable,
    CloudTableMetric,
    IngestEvent,
    Org,
)
from app.schemas import IngestRequest


def process_ingest(payload: IngestRequest, org: Org, db: Session) -> IngestEvent:
    """
    Upsert all sources/tables/files/fields/metrics from the payload.
    Returns the created IngestEvent.
    """
    event = IngestEvent(
        org_id=org.id,
        cli_version=payload.cli_version,
        source_count=len(payload.sources),
    )
    db.add(event)
    db.flush()  # get event.id

    for src_payload in payload.sources:
        source = (
            db.query(CloudSource)
            .filter(CloudSource.org_id == org.id, CloudSource.uri == src_payload.uri)
            .first()
        )
        if source is None:
            source = CloudSource(
                org_id=org.id,
                name=src_payload.name,
                type=src_payload.type,
                uri=src_payload.uri,
            )
            db.add(source)
        else:
            source.name = src_payload.name
            source.type = src_payload.type
        source.last_seen_at = datetime.datetime.utcnow()
        db.flush()

        for tbl_payload in src_payload.tables:
            table = (
                db.query(CloudTable)
                .filter(CloudTable.source_id == source.id, CloudTable.uri == tbl_payload.uri)
                .first()
            )
            if table is None:
                table = CloudTable(
                    source_id=source.id,
                    name=tbl_payload.name,
                    uri=tbl_payload.uri,
                    db_name=tbl_payload.db_name,
                    schema_name=tbl_payload.schema_name,
                )
                db.add(table)
            else:
                table.db_name = tbl_payload.db_name
                table.schema_name = tbl_payload.schema_name
            db.flush()

            for fld_payload in tbl_payload.fields:
                field = (
                    db.query(CloudField)
                    .filter(CloudField.table_id == table.id, CloudField.uri == fld_payload.uri)
                    .first()
                )
                if field is None:
                    field = CloudField(
                        table_id=table.id,
                        name=fld_payload.name,
                        type=fld_payload.type,
                        uri=fld_payload.uri,
                    )
                    db.add(field)
                else:
                    field.type = fld_payload.type

            for metric_payload in tbl_payload.metrics:
                ts = None
                if metric_payload.ts:
                    try:
                        ts = datetime.datetime.fromisoformat(metric_payload.ts)
                    except ValueError:
                        pass

                metric_value = None
                if metric_payload.metric_value is not None:
                    try:
                        metric_value = float(metric_payload.metric_value)
                    except (ValueError, TypeError):
                        pass

                metric = CloudTableMetric(
                    table_id=table.id,
                    ingest_event_id=event.id,
                    metric_name=metric_payload.metric_name,
                    metric_value=metric_value,
                    uri=metric_payload.uri,
                    ts=ts,
                )
                db.add(metric)

        for file_payload in src_payload.files:
            file = (
                db.query(CloudFile)
                .filter(CloudFile.source_id == source.id, CloudFile.uri == file_payload.uri)
                .first()
            )
            if file is None:
                file = CloudFile(
                    source_id=source.id,
                    name=file_payload.name,
                    uri=file_payload.uri,
                    filetype=file_payload.filetype,
                    file_encoding=file_payload.file_encoding,
                )
                db.add(file)
            else:
                file.filetype = file_payload.filetype
                file.file_encoding = file_payload.file_encoding
            db.flush()

            for fld_payload in file_payload.fields:
                field = (
                    db.query(CloudField)
                    .filter(CloudField.file_id == file.id, CloudField.uri == fld_payload.uri)
                    .first()
                )
                if field is None:
                    field = CloudField(
                        file_id=file.id,
                        name=fld_payload.name,
                        type=fld_payload.type,
                        uri=fld_payload.uri,
                    )
                    db.add(field)
                else:
                    field.type = fld_payload.type

    db.commit()
    db.refresh(event)
    return event
