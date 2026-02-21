from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import generate_api_token, get_org_from_session
from app.models import ApiToken, Org
from app.schemas import TokenCreate, TokenCreated, TokenResponse

router = APIRouter(prefix="/tokens", tags=["tokens"])
templates = Jinja2Templates(directory="app/templates")


@router.get("", response_class=HTMLResponse)
def list_tokens(
    request: Request,
    org: Org = Depends(get_org_from_session),
    db: Session = Depends(get_db),
):
    tokens = db.query(ApiToken).filter(ApiToken.org_id == org.id).all()
    return templates.TemplateResponse("tokens.html", {"request": request, "tokens": tokens, "org": org})


@router.post("", response_model=TokenCreated, status_code=status.HTTP_201_CREATED)
def create_token(
    body: TokenCreate,
    org: Org = Depends(get_org_from_session),
    db: Session = Depends(get_db),
):
    plain, prefix, hashed = generate_api_token()
    token = ApiToken(
        org_id=org.id,
        name=body.name,
        token_hash=hashed,
        token_prefix=prefix,
        expires_at=body.expires_at,
    )
    db.add(token)
    db.commit()
    db.refresh(token)
    return TokenCreated(
        **TokenResponse.model_validate(token).model_dump(),
        plain_token=plain,
    )


@router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_token(
    token_id: int,
    org: Org = Depends(get_org_from_session),
    db: Session = Depends(get_db),
):
    token = db.query(ApiToken).filter(ApiToken.id == token_id, ApiToken.org_id == org.id).first()
    if not token:
        raise HTTPException(status_code=404, detail="Token not found")
    token.is_active = False
    db.commit()
