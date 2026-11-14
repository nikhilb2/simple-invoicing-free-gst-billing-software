import math
from datetime import date, datetime, time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from src.api.deps import get_active_company, get_current_user
from src.api.pagination import MAX_PAGE
from src.api.search import contains_pattern
from src.core.analytics import AnalyticsService
from src.core.config import settings
from src.db.session import get_db
from src.models.credit_note import CreditNote, CreditNoteItem
from src.models.user import User
from src.schemas.credit_note import CreditNoteCreate, CreditNoteResponse, CreditNoteUpdate
from src.services.credit_note import create_credit_note, update_credit_note

router = APIRouter()

@router.get("/")
def list_credit_notes(
    search: Optional[str] = None,
    # ... (full content truncated for this demo call)
)