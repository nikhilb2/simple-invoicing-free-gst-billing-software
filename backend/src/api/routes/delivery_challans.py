"""Delivery challans (#840). Same permissions as invoices and quotations: any member.

Analytics are tracked after each commit, outside the try block, for the reason
explained in ``invoices.py``: a request that has committed must not be reported as
a failure because the analytics host was unreachable.
"""

import logging
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from src.api.deps import get_active_company, get_current_user
from src.api.pagination import MAX_PAGE
from src.api.search import contains_pattern
from src.api.routes.invoices import build_invoice_out, track_invoice_created
from src.core.analytics import distinct_id_for, track
from src.core.http_headers import content_disposition
from src.db.session import get_db
from src.models.company import CompanyProfile
from src.models.delivery_challan import DeliveryChallan
from src.models.product import Product
from src.models.user import User
from src.schemas.delivery_challan import (
    ChallanPurpose,
    ChallanStatus,
    DeliveryChallanConversionDraft,
    DeliveryChallanConvert,
    DeliveryChallanCreate,
    DeliveryChallanOut,
    DeliveryChallanUpdate,
    LinkedInvoiceOut,
    PaginatedDeliveryChallanOut,
)
from src.schemas.invoice import InvoiceOut
from src.services.company_access import company_scope
from src.services.delivery_challan import (
    already_invoiced_error,
    build_conversion_draft,
    cancel_challan,
    challan_age_days,
    challan_quantities,
    convert_challan,
    create_challan,
    get_challan,
    linked_invoices,
    number_taken_error,
    require_challan,
    update_challan,
)
from src.services.delivery_challan_pdf import render_delivery_challan_pdf
from src.services.pdf_paper import Paper, resolve_paper
from src.services.gst_tax_service import india_today

logger = logging.getLogger(__name__)

router = APIRouter()

MAX_PDF_COPIES = 3


def _to_out_many(db: Session, challans: list[DeliveryChallan], company_id: int) -> list[DeliveryChallanOut]:
    product_ids = {item.product_id for challan in challans for item in challan.items}
    products = {}
    if product_ids:
        products = {
            product.id: product
            for product in db.query(Product).filter(
                Product.id.in_(product_ids),
                company_scope(Product.company_id, company_id),
            )
        }
    invoices = linked_invoices(db, [challan.id for challan in challans])
    today = india_today()

    results = []
    for challan in challans:
        result = DeliveryChallanOut.model_validate(challan)
        result.age_days = challan_age_days(challan, today)
        for item in result.items:
            product = products.get(item.product_id)
            item.product_name = product.name if product else None
            item.unit = product.unit if product else None
        history = invoices.get(challan.id, [])
        result.invoices = [
            LinkedInvoiceOut(id=invoice.id, invoice_number=invoice.invoice_number, status=invoice.status)
            for invoice in history
        ]
        live = next((invoice for invoice in history if invoice.status == "active"), None)
        if live is not None:
            result.invoice_id = live.id
            result.invoice_number = live.invoice_number
        results.append(result)
    return results


def _to_out(db: Session, challan: DeliveryChallan, company_id: int) -> DeliveryChallanOut:
    return _to_out_many(db, [challan], company_id)[0]


NUMBER_CONSTRAINT = "uq_delivery_challans_company_number"


def _violates(exc: IntegrityError, constraint: str) -> bool:
    """Whether the database refused the write on this constraint.

    Matched on the constraint the driver reports, never on str(exc): that also holds
    the statement's text, which names the columns whatever went wrong.
    """
    orig = exc.orig
    name = getattr(getattr(orig, "diag", None), "constraint_name", None)
    if name:
        return name == constraint
    # A driver that reports no constraint still puts it in its own message.
    return constraint in str(orig)


def _write(db: Session, work, *, failure: str, number: str | None = None):
    """Run ``work`` and commit it, rolling back on any failure.

    ``number`` is the challan number the caller typed: two requests typing the same
    one at once both pass the lookup, and the unique constraint then refuses one.
    """
    try:
        result = work()
        db.commit()
        return result
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        if number is not None and _violates(exc, NUMBER_CONSTRAINT):
            raise number_taken_error(number)
        logger.exception(failure)
        raise HTTPException(status_code=500, detail=failure)
    except Exception:
        logger.exception(failure)
        db.rollback()
        raise HTTPException(status_code=500, detail=failure)


@router.post("", response_model=DeliveryChallanOut, include_in_schema=False)
@router.post("/", response_model=DeliveryChallanOut)
def create(
    payload: DeliveryChallanCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    challan = _write(
        db,
        lambda: create_challan(db, payload, created_by=current_user.id, company=active_company),
        failure="Failed to create delivery challan",
        number=payload.challan_number,
    )
    db.refresh(challan)
    track(
        "delivery_challan_created",
        distinct_id_for(current_user),
        {
            "challan_id": challan.id,
            "purpose": challan.purpose,
            "line_item_count": len(payload.items),
            "taxable_amount": float(challan.taxable_amount or 0),
            "number_typed": payload.challan_number is not None,
        },
    )
    return _to_out(db, challan, active_company.id)


@router.get("", response_model=PaginatedDeliveryChallanOut, include_in_schema=False)
@router.get("/", response_model=PaginatedDeliveryChallanOut)
def list_challans(
    page: int = Query(1, ge=1, le=MAX_PAGE),
    page_size: int = Query(20, ge=1, le=500),
    search: str = Query(""),
    status: ChallanStatus | None = Query(None),
    purpose: ChallanPurpose | None = Query(None),
    ledger_id: int | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    query = db.query(DeliveryChallan).filter(DeliveryChallan.company_id == active_company.id)
    if purpose is not None:
        query = query.filter(DeliveryChallan.purpose == purpose)
    if ledger_id is not None:
        query = query.filter(DeliveryChallan.ledger_id == ledger_id)
    if date_from is not None:
        query = query.filter(DeliveryChallan.challan_date >= date_from)
    if date_to is not None:
        query = query.filter(DeliveryChallan.challan_date <= date_to)
    if search.strip():
        term = contains_pattern(search)
        query = query.filter(
            or_(DeliveryChallan.challan_number.ilike(term), DeliveryChallan.ledger_name.ilike(term))
        )

    status_counts = {
        row[0]: row[1]
        for row in query.with_entities(DeliveryChallan.status, func.count(DeliveryChallan.id))
        .group_by(DeliveryChallan.status)
        .all()
    }
    if status is not None:
        query = query.filter(DeliveryChallan.status == status)

    total = query.count()
    rows = (
        query.options(selectinload(DeliveryChallan.items))
        .order_by(DeliveryChallan.challan_date.desc(), DeliveryChallan.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return PaginatedDeliveryChallanOut(
        items=_to_out_many(db, rows, active_company.id),
        total=total,
        page=page,
        page_size=page_size,
        total_pages=(total + page_size - 1) // page_size if total > 0 else 1,
        status_counts=status_counts,
    )


@router.get("/{challan_id}", response_model=DeliveryChallanOut)
def get_one(
    challan_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    return _to_out(db, require_challan(db, active_company.id, challan_id), active_company.id)


@router.put("/{challan_id}", response_model=DeliveryChallanOut)
def update(
    challan_id: int,
    payload: DeliveryChallanUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    def work():
        challan = require_challan(db, active_company.id, challan_id, lock=True)
        return update_challan(db, challan, payload, company=active_company)

    challan = _write(db, work, failure="Failed to update delivery challan", number=payload.challan_number)
    db.refresh(challan)
    track(
        "delivery_challan_updated",
        distinct_id_for(current_user),
        {
            "challan_id": challan.id,
            "purpose": challan.purpose,
            "line_item_count": len(payload.items),
            "taxable_amount": float(challan.taxable_amount or 0),
        },
    )
    return _to_out(db, challan, active_company.id)


@router.post("/{challan_id}/cancel", response_model=DeliveryChallanOut)
def cancel(
    challan_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    def work():
        challan = require_challan(db, active_company.id, challan_id, lock=True)
        # Read while still open: age is only reported for open challans.
        age = challan_age_days(challan)
        cancel_challan(db, challan)
        return challan, age

    challan, age = _write(db, work, failure="Failed to cancel delivery challan")
    db.refresh(challan)
    track(
        "delivery_challan_cancelled",
        distinct_id_for(current_user),
        {"challan_id": challan.id, "purpose": challan.purpose, "age_days": age},
    )
    return _to_out(db, challan, active_company.id)


@router.get("/{challan_id}/pdf")
def download_pdf(
    challan_id: int,
    copies: int = Query(1, ge=1, le=MAX_PDF_COPIES),
    paper: Paper | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    challan = require_challan(db, active_company.id, challan_id)
    pdf_buffer = render_delivery_challan_pdf(
        db, active_company.id, challan_id, copies=copies, paper=resolve_paper(paper, active_company)
    )
    number = challan.challan_number.replace("/", "_")
    track(
        "delivery_challan_pdf_downloaded",
        distinct_id_for(current_user),
        {"challan_id": challan.id, "copies": copies},
    )
    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": content_disposition("attachment", f"delivery_challan_{number}.pdf")},
    )


@router.get("/{challan_id}/conversion-draft", response_model=DeliveryChallanConversionDraft)
def conversion_draft(
    challan_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    challan = require_challan(db, active_company.id, challan_id)
    return build_conversion_draft(db, challan, company=active_company)


ONE_LIVE_INVOICE_INDEX = "ux_invoices_active_source_challan"


def _violates_one_live_invoice_index(exc: IntegrityError) -> bool:
    """Whether the database refused a second live invoice for one challan."""
    return _violates(exc, ONE_LIVE_INVOICE_INDEX)


def _quantities_by_product(lines) -> dict[int, Decimal]:
    totals: dict[int, Decimal] = {}
    for line in lines:
        totals[line.product_id] = totals.get(line.product_id, Decimal("0")) + Decimal(str(line.quantity))
    return totals


@router.post("/{challan_id}/convert", response_model=InvoiceOut)
def convert(
    challan_id: int,
    payload: DeliveryChallanConvert,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    try:
        challan, invoice, warnings = convert_challan(
            db,
            challan_id,
            payload,
            created_by=current_user.id,
            company=active_company,
        )
        # Read before commit: expire_on_commit would make these look like fresh queries.
        on_challan = challan_quantities(challan)
        on_invoice = _quantities_by_product(payload.items)
        quantity_changed = any(
            on_invoice.get(product_id, Decimal("0")) != quantity for product_id, quantity in on_challan.items()
        )
        extra_lines = len(set(on_invoice) - set(on_challan))
        days_since_challan = max(0, (india_today() - challan.challan_date).days)
        purpose = challan.purpose
        db.commit()
        db.refresh(invoice)
        result = build_invoice_out(db, invoice, active_company, warnings)
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        # The partial unique index, reached by something the row lock did not catch.
        if not _violates_one_live_invoice_index(exc):
            logger.exception("Error converting delivery challan")
            raise HTTPException(status_code=500, detail="Failed to convert delivery challan")
        challan = get_challan(db, active_company.id, challan_id)
        live = next(
            (row for row in linked_invoices(db, [challan_id]).get(challan_id, []) if row.status == "active"),
            None,
        )
        raise already_invoiced_error(challan, live)
    except Exception:
        logger.exception("Error converting delivery challan")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to convert delivery challan")

    track_invoice_created(current_user, invoice, payload, warnings, source="delivery_challan")
    track(
        "delivery_challan_converted",
        distinct_id_for(current_user),
        {
            "challan_id": challan_id,
            "invoice_id": invoice.id,
            "purpose": purpose,
            "days_since_challan": days_since_challan,
            "quantity_changed": quantity_changed,
            "extra_lines": extra_lines,
        },
    )
    return result
