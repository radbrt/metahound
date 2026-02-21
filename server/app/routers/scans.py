from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_org_from_session
from app.models import IngestEvent, Org

router = APIRouter(prefix="/scans", tags=["scans"])
templates = Jinja2Templates(directory="app/templates")


@router.get("", response_class=HTMLResponse)
def scans_page(
    request: Request,
    org: Org = Depends(get_org_from_session),
    db: Session = Depends(get_db),
):
    events = (
        db.query(IngestEvent)
        .filter(IngestEvent.org_id == org.id)
        .order_by(IngestEvent.received_at.desc())
        .limit(100)
        .all()
    )
    return templates.TemplateResponse("scans.html", {"request": request, "events": events, "org": org})
