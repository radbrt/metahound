from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_org_from_session
from app.models import Anomaly, CloudSource, IngestEvent, Org

router = APIRouter(tags=["dashboard"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
def home(
    request: Request,
    org: Org = Depends(get_org_from_session),
    db: Session = Depends(get_db),
):
    source_count = db.query(CloudSource).filter(CloudSource.org_id == org.id).count()
    open_anomalies = (
        db.query(Anomaly)
        .filter(Anomaly.org_id == org.id, Anomaly.is_acknowledged == False)
        .count()
    )
    recent_ingests = (
        db.query(IngestEvent)
        .filter(IngestEvent.org_id == org.id)
        .order_by(IngestEvent.received_at.desc())
        .limit(5)
        .all()
    )
    recent_anomalies = (
        db.query(Anomaly)
        .filter(Anomaly.org_id == org.id)
        .order_by(Anomaly.created_at.desc())
        .limit(10)
        .all()
    )
    return templates.TemplateResponse(
        "home.html",
        {
            "request": request,
            "org": org,
            "source_count": source_count,
            "open_anomalies": open_anomalies,
            "recent_ingests": recent_ingests,
            "recent_anomalies": recent_anomalies,
        },
    )
