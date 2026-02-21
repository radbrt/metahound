from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_org_from_session
from app.models import CloudSource, CloudTable, Org

router = APIRouter(prefix="/sources", tags=["sources"])
templates = Jinja2Templates(directory="app/templates")


@router.get("", response_class=HTMLResponse)
def sources_page(
    request: Request,
    org: Org = Depends(get_org_from_session),
    db: Session = Depends(get_db),
):
    sources = db.query(CloudSource).filter(CloudSource.org_id == org.id).order_by(CloudSource.last_seen_at.desc()).all()
    return templates.TemplateResponse("sources.html", {"request": request, "sources": sources, "org": org})


@router.get("/{source_id}", response_class=HTMLResponse)
def source_detail(
    source_id: int,
    request: Request,
    org: Org = Depends(get_org_from_session),
    db: Session = Depends(get_db),
):
    source = db.query(CloudSource).filter(CloudSource.id == source_id, CloudSource.org_id == org.id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    tables = db.query(CloudTable).filter(CloudTable.source_id == source.id).all()
    return templates.TemplateResponse(
        "source_detail.html",
        {"request": request, "source": source, "tables": tables, "org": org},
    )
