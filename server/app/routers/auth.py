"""
Auth0 Authorization Code flow.
"""
import secrets

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Org

router = APIRouter(prefix="/auth", tags=["auth"])


def _auth0_authorize_url(state: str, redirect_uri: str) -> str:
    return (
        f"https://{settings.auth0_domain}/authorize"
        f"?response_type=code"
        f"&client_id={settings.auth0_client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&scope=openid+profile+email"
        f"&audience={settings.auth0_audience}"
        f"&state={state}"
    )


@router.get("/login")
def login(request: Request):
    state = secrets.token_urlsafe(16)
    request.session["oauth_state"] = state
    redirect_uri = f"{settings.app_base_url}/auth/callback"
    return RedirectResponse(_auth0_authorize_url(state, redirect_uri))


@router.get("/callback")
def callback(request: Request, code: str, state: str, db: Session = Depends(get_db)):
    if state != request.session.get("oauth_state"):
        raise HTTPException(status_code=400, detail="State mismatch")

    redirect_uri = f"{settings.app_base_url}/auth/callback"
    token_url = f"https://{settings.auth0_domain}/oauth/token"
    resp = httpx.post(
        token_url,
        json={
            "grant_type": "authorization_code",
            "client_id": settings.auth0_client_id,
            "client_secret": settings.auth0_client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        },
        timeout=10,
    )
    resp.raise_for_status()
    tokens = resp.json()

    # Decode the access token to extract the org_slug custom claim
    from jose import jwt as jose_jwt
    access_token = tokens.get("access_token", "")
    try:
        claims = jose_jwt.get_unverified_claims(access_token)
    except Exception:
        claims = {}

    org_slug = claims.get("https://metadog.io/org_slug")
    if not org_slug:
        raise HTTPException(status_code=400, detail="No org_slug claim in token")

    org = db.query(Org).filter(Org.slug == org_slug).first()
    if not org:
        raise HTTPException(status_code=403, detail=f"Org '{org_slug}' not found")

    request.session["org_slug"] = org_slug
    return RedirectResponse("/")


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    logout_url = (
        f"https://{settings.auth0_domain}/v2/logout"
        f"?client_id={settings.auth0_client_id}"
        f"&returnTo={settings.app_base_url}"
    )
    return RedirectResponse(logout_url)
