from datetime import date
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from src.core.config import settings
from src.models.financial_year import FinancialYear


def _require_company_in_shared_hosting(company_id: int | None) -> None:
    """No company means "every company's FYs" -- only safe on a single-tenant DB."""
    if company_id is None and settings.is_shared_hosting:
        raise ValueError("A company_id is required in shared hosting")


def get_active_fy(db: Session, company_id: int | None = None) -> Optional[FinancialYear]:
    """Return the currently active financial year, or None if none is set."""
    _require_company_in_shared_hosting(company_id)
    query = db.query(FinancialYear).filter(FinancialYear.is_active.is_(True))
    if company_id is not None:
        query = query.filter(FinancialYear.company_id == company_id)
    return query.first()


def get_fy_for_date(db: Session, invoice_date: date, company_id: int | None = None) -> Optional[FinancialYear]:
    """Return the financial year whose range contains invoice_date, or None."""
    _require_company_in_shared_hosting(company_id)
    query = db.query(FinancialYear).filter(
        FinancialYear.start_date <= invoice_date,
        FinancialYear.end_date >= invoice_date,
    )
    if company_id is not None:
        query = query.filter(FinancialYear.company_id == company_id)
    return query.first()


def _fy_name(label: str) -> str:
    """ "2026-27" -> "FY 2026-27"; a label that already says FY is kept as it is."""
    return label if label.strip().upper().startswith("FY") else f"FY {label}"


def _indian_fy_label(day: date) -> str:
    """The April-to-March financial year a date falls in, e.g. "2027-28" for 1 Apr 2027."""
    start_year = day.year if day.month >= 4 else day.year - 1
    return f"{start_year}-{str(start_year + 1)[-2:]}"


def require_financial_year_for_date(db: Session, doc_date: date, company_id: int | None = None) -> None:
    """Refuse a document date that none of the company's financial years covers.

    Numbers run per financial year, so a document dated outside every year would
    be numbered and filed in a year that does not contain its date (#1132): an
    April 2027 invoice as INV-2026-021, counted in GSTR-1 for April 2027. A new
    year is an accounting decision, so it is never created here; the user adds it
    or picks another date. A company with no financial years at all still uses the
    year-less numbering, so it is left alone.
    """
    if get_fy_for_date(db, doc_date, company_id=company_id) is not None:
        return
    query = db.query(FinancialYear)
    if company_id is not None:
        query = query.filter(FinancialYear.company_id == company_id)
    years = query.order_by(FinancialYear.start_date.desc()).all()
    if not years:
        return
    # The year the user is working in, as the sidebar shows it, else the latest one.
    suggested = next((fy for fy in years if fy.is_active), years[0])
    raise HTTPException(
        status_code=400,
        detail=(
            f"This date is in {_fy_name(_indian_fy_label(doc_date))}, which isn't set up yet. "
            f"An admin can add it from the side menu (Financial Year \u2192 + New FY). "
            f"Or pick a date in {_fy_name(suggested.label)}."
        ),
    )


def require_same_financial_year(
    db: Session,
    current_fy_id: int | None,
    new_date: date,
    *,
    company_id: int,
    document: str,
) -> None:
    """Refuse a date edit that would move an issued document into another financial year.

    The financial year and the number series are fixed when the document is issued,
    so the number would keep the old year while lists and reports file it under the
    new one. A date that no financial year covers is refused too (#1132).
    """
    if current_fy_id is None:
        return
    date_fy = get_fy_for_date(db, new_date, company_id=company_id)
    if date_fy is None:
        require_financial_year_for_date(db, new_date, company_id=company_id)
        return
    if date_fy.id == current_fy_id:
        return
    current_fy = db.query(FinancialYear).filter(FinancialYear.id == current_fy_id).first()
    current_label = current_fy.label if current_fy else f"id {current_fy_id}"
    raise HTTPException(
        status_code=400,
        detail=(
            f"This date is in {date_fy.label}, but the {document} belongs to "
            f"{current_label}. Cancel it and create a new {document} in "
            f"{date_fy.label} instead."
        ),
    )


def activate_fy(db: Session, fy_id: int, company_id: int | None = None) -> FinancialYear:
    """Set the target FY as active; deactivate all others atomically."""
    _require_company_in_shared_hosting(company_id)
    target_query = db.query(FinancialYear).filter(FinancialYear.id == fy_id)
    if company_id is not None:
        target_query = target_query.filter(FinancialYear.company_id == company_id)
    target = target_query.first()
    if not target:
        return None

    deactivate_query = db.query(FinancialYear).filter(FinancialYear.is_active.is_(True))
    if company_id is not None:
        deactivate_query = deactivate_query.filter(FinancialYear.company_id == company_id)

    deactivate_query.update(
        {"is_active": False}, synchronize_session="fetch"
    )
    target.is_active = True
    db.commit()
    db.refresh(target)
    return target
