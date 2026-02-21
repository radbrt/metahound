from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_org_from_api_token
from app.models import Org
from app.schemas import IngestRequest, IngestResponse
from app.services.anomaly_service import detect_anomalies_for_ingest
from app.services.ingest_service import process_ingest
from app.tasks.scheduler import schedule_alert_job

router = APIRouter(prefix="/api/v1", tags=["ingest"])


@router.post("/ingest", response_model=IngestResponse)
def ingest(
    payload: IngestRequest,
    org: Org = Depends(get_org_from_api_token),
    db: Session = Depends(get_db),
):
    event = process_ingest(payload, org, db)

    tables_processed = sum(len(s.tables) for s in payload.sources)
    anomalies = detect_anomalies_for_ingest(event, org, db)

    if anomalies and org.alerts_enabled:
        from app.database import SessionLocal
        schedule_alert_job(org, anomalies, SessionLocal)

    return IngestResponse(
        ingest_event_id=event.id,
        sources_processed=len(payload.sources),
        tables_processed=tables_processed,
        anomalies_detected=len(anomalies),
    )
