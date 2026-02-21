"""
Z-score anomaly detection on newly ingested metrics.
"""
import datetime

import numpy as np
from sqlalchemy.orm import Session

from app.models import Anomaly, CloudTableMetric, IngestEvent, Org

_MIN_POINTS = 3
_Z_THRESHOLD = 3.0


def detect_anomalies_for_ingest(event: IngestEvent, org: Org, db: Session) -> list[Anomaly]:
    """
    For every distinct metric URI touched by this ingest event, run Z-score detection
    over the full history. Returns newly created Anomaly rows.
    """
    # Collect metric URIs written in this ingest event
    new_metrics = (
        db.query(CloudTableMetric)
        .filter(CloudTableMetric.ingest_event_id == event.id)
        .all()
    )

    seen_uris: set[str] = set()
    anomalies: list[Anomaly] = []

    for new_metric in new_metrics:
        uri = new_metric.uri
        if uri in seen_uris:
            continue
        seen_uris.add(uri)

        # Fetch full history for this metric URI (ordered by ts)
        history = (
            db.query(CloudTableMetric)
            .filter(
                CloudTableMetric.uri == uri,
                CloudTableMetric.metric_value.isnot(None),
            )
            .order_by(CloudTableMetric.ts)
            .all()
        )

        if len(history) < _MIN_POINTS:
            continue

        values = np.array([m.metric_value for m in history], dtype=float)
        mean = values.mean()
        std = values.std()

        if std == 0:
            continue

        # Check only the points from this ingest event
        ingest_metrics = [m for m in history if m.ingest_event_id == event.id]
        for m in ingest_metrics:
            z = abs((m.metric_value - mean) / std)
            if z >= _Z_THRESHOLD:
                anomaly = Anomaly(
                    org_id=org.id,
                    ingest_event_id=event.id,
                    metric_uri=uri,
                    metric_name=m.metric_name,
                    table_uri=m.table.uri if m.table else uri,
                    anomaly_ts=m.ts,
                    observed_value=m.metric_value,
                    z_score=float(z),
                    algorithm="zscore",
                )
                db.add(anomaly)
                anomalies.append(anomaly)

    if anomalies:
        db.commit()
        for a in anomalies:
            db.refresh(a)

    return anomalies
