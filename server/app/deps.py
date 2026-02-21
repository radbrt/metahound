"""
Authentication dependencies for FastAPI routes.

Two auth paths:
  1. JWT (Auth0) — used by the web UI after Auth0 login
  2. API token (bcrypt) — used by `metadog push` via Bearer header
"""
import datetime
import secrets

import bcrypt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import ApiToken, Org

bearer_scheme = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# Auth0 JWT verification
# ---------------------------------------------------------------------------

def _get_jwks():
    import httpx
    url = f"https://{settings.auth0_domain}/.well-known/jwks.json"
    resp = httpx.get(url, timeout=10)
    resp.raise_for_status()
    return resp.json()


def verify_jwt(token: str) -> dict:
    """Decode and verify an Auth0 JWT. Returns the payload."""
    try:
        jwks = _get_jwks()
        unverified_header = jwt.get_unverified_header(token)
        rsa_key = {}
        for key in jwks["keys"]:
            if key["kid"] == unverified_header["kid"]:
                rsa_key = {
                    "kty": key["kty"],
                    "kid": key["kid"],
                    "use": key["use"],
                    "n": key["n"],
                    "e": key["e"],
                }
        if not rsa_key:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token key")

        payload = jwt.decode(
            token,
            rsa_key,
            algorithms=["RS256"],
            audience=settings.auth0_audience,
            issuer=f"https://{settings.auth0_domain}/",
        )
        return payload
    except JWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))


# ---------------------------------------------------------------------------
# API token verification (for CLI push)
# ---------------------------------------------------------------------------

def _verify_api_token(plain_token: str, db: Session) -> ApiToken:
    """Look up token by 8-char prefix, then bcrypt-verify the full token."""
    if len(plain_token) < 8:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    prefix = plain_token[:8]
    token_row = (
        db.query(ApiToken)
        .filter(ApiToken.token_prefix == prefix, ApiToken.is_active == True)
        .first()
    )
    if token_row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    if token_row.expires_at and token_row.expires_at < datetime.datetime.utcnow():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")

    if not bcrypt.checkpw(plain_token.encode(), token_row.token_hash.encode()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    token_row.last_used_at = datetime.datetime.utcnow()
    db.commit()
    return token_row


def get_org_from_api_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> Org:
    """FastAPI dependency: authenticates via API token and returns the owning Org."""
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    token_row = _verify_api_token(credentials.credentials, db)
    return token_row.org


# ---------------------------------------------------------------------------
# Session-based org (web UI after Auth0 login)
# ---------------------------------------------------------------------------

def get_org_from_session(request: Request, db: Session = Depends(get_db)) -> Org:
    """FastAPI dependency: resolves org from the signed session cookie set after Auth0 login."""
    org_slug = request.session.get("org_slug")
    if not org_slug:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not logged in")
    org = db.query(Org).filter(Org.slug == org_slug).first()
    if not org:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Org not found")
    return org


# ---------------------------------------------------------------------------
# Token creation helper (used by tokens router)
# ---------------------------------------------------------------------------

def generate_api_token() -> tuple[str, str, str]:
    """Return (plain_token, prefix, bcrypt_hash)."""
    plain = secrets.token_urlsafe(32)
    prefix = plain[:8]
    hashed = bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()
    return plain, prefix, hashed
