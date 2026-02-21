from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_org_from_session
from app.models import Anomaly, Org
from app.schemas import AnomalyResponse

router = APIRouter(prefix="/anomalies", tags=["anomalies"])
templates = Jinja2Templates(directory="app/templates")


@router.get("", response_class=HTMLResponse)
def list_anomalies(
    request: Request,
    unacknowledged_only: bool = False,
    org: Org = Depends(get_org_from_session),
    db: Session = Depends(get_db),
):
    q = db.query(Anomaly).filter(Anomaly.org_id == org.id)
    if unacknowledged_only:
        q = q.filter(Anomaly.is_acknowledged == False)
    anomalies = q.order_by(Anomaly.created_at.desc()).all()

    # HTMX partial swap: return only rows if requested via HX-Request header
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            "partials/anomaly_row.html",
            {"request": request, "anomalies": anomalies},
        )
    return templates.TemplateResponse(
        "anomalies.html",
        {"request": request, "anomalies": anomalies, "org": org},
    )


@router.patch("/{anomaly_id}/acknowledge", response_class=HTMLResponse)
def acknowledge_anomaly(
    anomaly_id: int,
    request: Request,
    org: Org = Depends(get_org_from_session),
    db: Session = Depends(get_db),
):
    anomaly = db.query(Anomaly).filter(Anomaly.id == anomaly_id, Anomaly.org_id == org.id).first()
    if not anomaly:
        raise HTTPException(status_code=404, detail="Anomaly not found")
    anomaly.is_acknowledged = True
    db.commit()
    db.refresh(anomaly)
    return templates.TemplateResponse(
        "partials/anomaly_row.html",
        {"request": request, "anomalies": [anomaly]},
    )
