"""Support contact clicks.

The WhatsApp support bubble is a link to wa.me that leaves the app, so the
browser reports the click here and the event is captured server-side, like
every other product event (see src/core/analytics.py).

The bubble is on every screen, the login page included, so this route takes an
optional sign-in: a signed-in operator is keyed by email, a visitor by the
browser's anonymous PostHog id. It never answers 401, because the API client
answers a 401 by trying a token refresh, and a support click must not log
anyone out.

`include_in_schema=False` keeps it out of the MCP tool registry, which builds a
tool from every operation in the OpenAPI schema.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.api.deps import get_current_user
from src.core.analytics import distinct_id_for, track
from src.core.rate_limit import TokenBucket, client_ip
from src.core.utm import clean_utm
from src.db.session import get_db
from src.models.user import User

router = APIRouter()

_optional_token = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

# Unauthenticated and writes to PostHog, so one address cannot pad the count.
# PER REPLICA, like every bucket in src/core/rate_limit.py.
_click_bucket = TokenBucket(capacity=10, refill_per_second=0.2)

class WhatsAppClick(BaseModel):
    # The UTM tags the visitor arrived with, kept by the browser since landing.
    utm: dict[str, str] = Field(default_factory=dict)
    # The browser's PostHog distinct id, used only when nobody is signed in.
    anonymous_id: Optional[str] = Field(default=None, max_length=200)
    # The app path the bubble was clicked on, e.g. /invoices.
    path: Optional[str] = Field(default=None, max_length=500)


def _optional_user(
    token: Optional[str] = Depends(_optional_token),
    db: Session = Depends(get_db),
) -> Optional[User]:
    if not token:
        return None
    try:
        return get_current_user(token, db)
    except HTTPException:
        return None


@router.post("/whatsapp-click", status_code=204, include_in_schema=False)
def whatsapp_click(
    body: WhatsAppClick,
    request: Request,
    user: Optional[User] = Depends(_optional_user),
) -> Response:
    """Records `support_whatsapp_clicked`. Always 204: the chat opens regardless."""
    if _click_bucket.hit(client_ip(request)):
        return Response(status_code=204)

    distinct_id = distinct_id_for(user) if user is not None else (body.anonymous_id or None)
    properties: dict = {
        "signed_in": user is not None,
        **clean_utm(body.utm),
    }
    if body.path:
        properties["path"] = body.path
    track("support_whatsapp_clicked", distinct_id, properties)
    return Response(status_code=204)
