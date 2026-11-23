"""Delivery challans (#840): everything short of the PDF, the e-way bill and the routes.

A challan moves stock and nothing else. It holds its goods out of stock only while it
is ``open``; once invoiced, that hold is released and the invoice's own sale stands;
a cancelled challan holds nothing. So for every product that keeps inventory:

    stock == opening + purchases - sales - (quantities on open challans)

with every movement below keeping that true:

    Challan saved                   -C
    Challan edited (open)           -(C_new - C_old)
    Challan cancelled (open)        +C
    Converted                       +C (release), then the invoice's normal -I
    Invoice from a challan edited   the invoice's normal delta, nothing here
    That invoice cancelled          the invoice's normal +I, then the challan reopens: -C
    That invoice restored           challan open: +C (release), then the invoice's -I

These functions flush but never commit; the routes own the transaction. Lock order is
always the challan, then (a quotation,) the invoice, then the series and stock rows,
which is why the invoice cancel and restore hooks take the challan before anything.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy.orm import Session

from src.core.document_limits import QUANTITY_LIMIT
from src.core.validation import GSTR1_DOCUMENT_NUMBER_RULE, is_gstr1_document_number
from src.models.company import CompanyProfile
from src.models.delivery_challan import (
    STATUS_CANCELLED,
    STATUS_INVOICED,
    STATUS_OPEN,
    DeliveryChallan,
    DeliveryChallanItem,
)
from src.models.invoice import Invoice
from src.models.product import Product
from src.schemas.delivery_challan import (
    ChallanConversionLine,
    ConversionWarning,
    DeliveryChallanConversionDraft,
    DeliveryChallanConvert,
    DeliveryChallanCreate,
    DeliveryChallanFields,
    DeliveryChallanUpdate,
)
from src.schemas.invoice import InvoiceItemCreate
from src.services.company_access import company_scope
from src.services.document_totals import require_money_fits, snapshot_company_fields
from src.services.financial_year import get_active_fy, get_fy_for_date, require_same_financial_year
from src.services.gst_tax_service import (
    assign_invoice_tax_totals,
    assign_item_tax_split,
    default_place_of_supply,
    india_today,
    invoice_is_interstate,
    money as _money,
)
from src.services.inventory_service import InventoryManager
from src.services.invoice_creation import create_invoice_record
from src.services.invoice_processor import InvoiceProcessor
from src.services.quotation import (
    _apply_shipping,
    _orphaned_snapshot,
    _usable_shipping_address_id,
)
from src.services.series import generate_next_number

CHALLAN_DOCUMENT = "this delivery challan"


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def get_challan(db: Session, company_id: int, challan_id: int, *, lock: bool = False) -> DeliveryChallan | None:
    """One challan inside the company, optionally with its row locked.

    Never joinedload here: Postgres refuses FOR UPDATE across an outer join. Items
    load lazily afterwards. populate_existing because a lock is pointless if the
    session then answers from a copy it read before waiting for that lock.
    """
    query = db.query(DeliveryChallan).filter(
        DeliveryChallan.id == challan_id,
        DeliveryChallan.company_id == company_id,
    )
    if lock:
        query = query.populate_existing().with_for_update()
    return query.first()


def require_challan(db: Session, company_id: int, challan_id: int, *, lock: bool = False) -> DeliveryChallan:
    challan = get_challan(db, company_id, challan_id, lock=lock)
    if challan is None:
        raise HTTPException(status_code=404, detail=f"Delivery challan {challan_id} not found")
    return challan


def linked_invoices(db: Session, challan_ids: list[int]) -> dict[int, list]:
    """Id, number and status of every invoice made from these challans, oldest first."""
    if not challan_ids:
        return {}
    rows = (
        db.query(Invoice.id, Invoice.source_challan_id, Invoice.invoice_number, Invoice.status)
        .filter(Invoice.source_challan_id.in_(challan_ids))
        .order_by(Invoice.id)
        .all()
    )
    grouped: dict[int, list] = {}
    for row in rows:
        grouped.setdefault(row.source_challan_id, []).append(row)
    return grouped


def _active_invoice(db: Session, challan_id: int, *, excluding: int | None = None) -> Invoice | None:
    query = db.query(Invoice).filter(
        Invoice.source_challan_id == challan_id,
        Invoice.status == "active",
    )
    if excluding is not None:
        query = query.filter(Invoice.id != excluding)
    return query.first()


# ---------------------------------------------------------------------------
# Stock
# ---------------------------------------------------------------------------

def challan_quantities(challan: DeliveryChallan) -> dict[int, Decimal]:
    """product_id -> the quantity summed over the challan's lines."""
    totals: dict[int, Decimal] = {}
    for item in challan.items:
        totals[item.product_id] = totals.get(item.product_id, Decimal("0")) + Decimal(str(item.quantity))
    return totals


def _move_challan_stock(
    db: Session,
    company_id: int,
    deltas: dict[int, Decimal],
    *,
    document: str,
    context: str,
) -> None:
    """Apply signed stock changes (negative = goods out) for the products that keep stock.

    Every shortfall is checked before anything moves, so a refusal is a clean
    ``insufficient_stock`` 400 rather than a half-applied change. The flag is read
    now, as reverse_invoice_inventory does: a product that stopped keeping stock is
    left alone.
    """
    moves: list[tuple[Product, Decimal]] = []
    for product_id, delta in deltas.items():
        if delta == 0:
            continue
        product = (
            db.query(Product)
            .filter(Product.id == product_id, company_scope(Product.company_id, company_id))
            .first()
        )
        if product is None:
            raise HTTPException(status_code=404, detail=f"Product {product_id} not found")
        if not product.maintain_inventory:
            continue
        if product.track_serials:
            # Challan stock has no serial rows, so moving it would break "stock equals
            # the serials in stock". Product updates refuse to turn tracking on while
            # an open challan holds the product; this catches what is left, such as
            # re-opening a challan whose product became serial-numbered after invoicing.
            raise HTTPException(
                status_code=400,
                detail=(
                    f"{product.name} is now serial-numbered, and a delivery challan can't move "
                    "its stock. Turn off serial numbers for it first."
                ),
            )
        moves.append((product, delta))

    inventory = InventoryManager(db)
    for product, delta in moves:
        if delta < 0:
            inventory.check_availability(
                product.id,
                -delta,
                company_id=company_id,
                product_name=product.name,
                document=document,
            )
    for product, delta in moves:
        inventory.update_quantity(
            product.id,
            delta,
            company_id=company_id,
            context=context,
            product_name=product.name,
        )


def _take_out(db: Session, challan: DeliveryChallan, *, document: str, context: str) -> None:
    _move_challan_stock(
        db,
        challan.company_id,
        {product_id: -quantity for product_id, quantity in challan_quantities(challan).items()},
        document=document,
        context=context,
    )


def _release(db: Session, challan: DeliveryChallan, *, context: str) -> None:
    _move_challan_stock(
        db,
        challan.company_id,
        challan_quantities(challan),
        document=CHALLAN_DOCUMENT,
        context=context,
    )


# ---------------------------------------------------------------------------
# Create and edit
# ---------------------------------------------------------------------------

def _require_number_format(number: str) -> None:
    if not is_gstr1_document_number(number):
        raise HTTPException(
            status_code=400,
            detail=f"Challan number must be {GSTR1_DOCUMENT_NUMBER_RULE}.",
        )


def number_taken_error(number: str) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": "challan_number_taken",
            "message": f"Challan number {number} is already used. Pick another.",
        },
    )


def _require_number_free(db: Session, company_id: int, number: str, *, excluding: int | None = None) -> None:
    query = db.query(DeliveryChallan.id).filter(
        DeliveryChallan.company_id == company_id,
        DeliveryChallan.challan_number == number,
    )
    if excluding is not None:
        query = query.filter(DeliveryChallan.id != excluding)
    if query.first() is not None:
        raise number_taken_error(number)


def _refuse_serial_products(validated: list[tuple]) -> None:
    """Serial-numbered goods are refused rather than half-supported (v1)."""
    for _, product, _ in validated:
        if product.track_serials:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"{product.name} is serial-numbered. Delivery challans don't support "
                    "serial-numbered products yet, so bill it on an invoice instead."
                ),
            )


def _apply_payload(
    db: Session,
    challan: DeliveryChallan,
    payload: DeliveryChallanFields,
    company: CompanyProfile,
    *,
    creating: bool,
    kept_snapshot: tuple[str, str] | None = None,
) -> None:
    """Snapshot the parties and price the lines, with the arithmetic invoices use."""
    processor = InvoiceProcessor(db)
    ledger = processor.require_ledger(payload.ledger_id, company.id)

    challan.ledger_id = ledger.id
    challan.ledger_name = ledger.name
    challan.ledger_address = ledger.address
    challan.ledger_gst = ledger.gst
    challan.ledger_phone = ledger.phone_number
    snapshot_company_fields(challan, company)
    challan.purpose = payload.purpose
    challan.reference_notes = payload.reference_notes

    if "terms_text" in payload.model_fields_set:
        challan.terms_text = (payload.terms_text or "").strip() or None
    elif creating:
        challan.terms_text = challan.company_terms_text

    # A seller with no GSTIN has no state to compare, as on an invoice.
    if not (company.gst or "").strip():
        challan.place_of_supply = None
    else:
        challan.place_of_supply = payload.place_of_supply or default_place_of_supply(company.gst, ledger.gst)

    _apply_shipping(db, challan, payload, company.id, kept_snapshot=kept_snapshot)

    validated = processor.resolve_items(payload.items, company.id, document_label="Delivery challan")
    # NUMERIC(12, 3) rounds before checking the bound, as in validate_items.
    for _, product, quantity in validated:
        if quantity >= Decimal(QUANTITY_LIMIT) - Decimal("0.0005"):
            raise HTTPException(
                status_code=400,
                detail=f"Quantity for {product.name} must stay below {QUANTITY_LIMIT:,} after rounding.",
            )
    _refuse_serial_products(validated)

    items: list[DeliveryChallanItem] = []
    for result in processor.calculate_totals(validated, False):
        require_money_fits(
            f"The amounts for {result['product'].name}",
            result["unit_price"],
            result["taxable_amount"],
            result["tax_amount"],
            result["line_total"],
        )
        items.append(
            DeliveryChallanItem(
                product_id=result["product"].id,
                quantity=float(result["quantity_value"]),
                hsn_sac=result["product"].hsn_sac,
                unit_price=float(result["unit_price"]),
                gst_rate=float(result["gst_rate"]),
                taxable_amount=float(result["taxable_amount"]),
                tax_amount=float(result["tax_amount"]),
                line_total=float(result["line_total"]),
                description=result["item_schema"].description,
            )
        )
    challan.items = items

    interstate = invoice_is_interstate(challan)
    assign_item_tax_split(items, interstate_supply=interstate, tax_inclusive=False)
    taxable_total = _money(sum((Decimal(str(item.taxable_amount or 0)) for item in items), Decimal("0")))
    challan.taxable_amount = float(taxable_total)
    tax_total = assign_invoice_tax_totals(challan, items, interstate_supply=interstate)
    total = _money(taxable_total + tax_total)
    challan.total_amount = float(total)
    require_money_fits("The total of this delivery challan", taxable_total, tax_total, total)


def create_challan(
    db: Session,
    payload: DeliveryChallanCreate,
    *,
    created_by: int,
    company: CompanyProfile,
) -> DeliveryChallan:
    """A new open challan on its own number series. Takes its goods out of stock."""
    challan_date = payload.challan_date or india_today()
    active_fy = get_active_fy(db, company_id=company.id)
    fy = get_fy_for_date(db, challan_date, company_id=company.id) or active_fy
    fy_id = fy.id if fy else None

    if payload.challan_number is not None:
        _require_number_format(payload.challan_number)
        _require_number_free(db, company.id, payload.challan_number)
        number = payload.challan_number
    else:
        number = generate_next_number(
            db,
            "delivery_challan",
            fy_id,
            challan_date,
            active_fy.id if active_fy else None,
            company_id=company.id,
        )
        if not is_gstr1_document_number(number):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"The delivery challan series gives numbers like {number}, but a challan number must be "
                    f"{GSTR1_DOCUMENT_NUMBER_RULE}. Shorten the format in Settings > Company, or type a number."
                ),
            )

    challan = DeliveryChallan(
        company_id=company.id,
        challan_number=number,
        status=STATUS_OPEN,
        challan_date=challan_date,
        financial_year_id=fy_id,
        created_by=created_by,
    )
    # Added only once the required columns are filled: the lookups in _apply_payload
    # would otherwise autoflush a half-built row.
    _apply_payload(db, challan, payload, company, creating=True)
    db.add(challan)
    db.flush()
    _take_out(db, challan, document=CHALLAN_DOCUMENT, context=f"saving delivery challan {number}")
    return challan


def _not_open_error(challan: DeliveryChallan, action: str) -> HTTPException:
    article = "An" if challan.status == STATUS_INVOICED else "A"
    return HTTPException(
        status_code=400,
        detail=f"{article} {challan.status} delivery challan cannot be {action}",
    )


def update_challan(
    db: Session,
    challan: DeliveryChallan,
    payload: DeliveryChallanUpdate,
    *,
    company: CompanyProfile,
) -> DeliveryChallan:
    """Replace the fields and lines of an open challan, and move stock by the difference."""
    if challan.status != STATUS_OPEN:
        raise _not_open_error(challan, "edited")

    if payload.challan_number is not None and payload.challan_number != challan.challan_number:
        _require_number_format(payload.challan_number)
        _require_number_free(db, company.id, payload.challan_number, excluding=challan.id)
        challan.challan_number = payload.challan_number

    challan_date = payload.challan_date or challan.challan_date
    if challan_date != challan.challan_date:
        if challan.financial_year_id is None:
            fy = get_fy_for_date(db, challan_date, company_id=company.id)
            if fy is not None:
                challan.financial_year_id = fy.id
        else:
            require_same_financial_year(
                db, challan.financial_year_id, challan_date, company_id=company.id, document="delivery challan"
            )
    challan.challan_date = challan_date

    old = challan_quantities(challan)
    kept_snapshot = _orphaned_snapshot(challan)
    # Clear first: a delete-orphan replacement would otherwise flush inserts and
    # deletes in whichever order suits the unit of work.
    challan.items = []
    db.flush()
    _apply_payload(db, challan, payload, company, creating=False, kept_snapshot=kept_snapshot)
    challan.updated_at = datetime.utcnow()
    db.flush()

    new = challan_quantities(challan)
    deltas = {
        product_id: old.get(product_id, Decimal("0")) - new.get(product_id, Decimal("0"))
        for product_id in set(old) | set(new)
    }
    _move_challan_stock(
        db,
        company.id,
        deltas,
        document=CHALLAN_DOCUMENT,
        context=f"editing delivery challan {challan.challan_number}",
    )
    return challan


def cancel_challan(db: Session, challan: DeliveryChallan) -> None:
    """Cancel an open challan and put its goods back. It keeps its number."""
    if challan.status == STATUS_CANCELLED:
        raise HTTPException(status_code=400, detail="Delivery challan is already cancelled")
    if challan.status == STATUS_INVOICED:
        live = _active_invoice(db, challan.id)
        number = live.invoice_number if live is not None else "an invoice"
        raise HTTPException(
            status_code=400,
            detail=f"This delivery challan has a live invoice ({number}). Cancel the invoice first.",
        )
    challan.status = STATUS_CANCELLED
    challan.cancelled_at = datetime.utcnow()
    challan.updated_at = challan.cancelled_at
    _release(db, challan, context=f"cancelling delivery challan {challan.challan_number}")


# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------

def already_invoiced_error(challan: DeliveryChallan, invoice: Invoice | None) -> HTTPException:
    """The 409 a second conversion gets, naming the invoice that already exists."""
    number = invoice.invoice_number if invoice is not None else None
    return HTTPException(
        status_code=409,
        detail={
            "code": "challan_already_invoiced",
            "message": (
                f"{challan.challan_number} was already invoiced as {number}"
                if number
                else f"{challan.challan_number} was already invoiced"
            ),
            "invoice_id": invoice.id if invoice is not None else None,
            "invoice_number": number,
        },
    )


def _require_convertible(db: Session, challan: DeliveryChallan) -> None:
    if challan.status == STATUS_INVOICED:
        raise already_invoiced_error(challan, _active_invoice(db, challan.id))
    if challan.status == STATUS_CANCELLED:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "challan_cancelled",
                "message": f"{challan.challan_number} is cancelled and cannot be invoiced",
            },
        )
    # The status check and the row lock settle the normal race; this catches a live
    # invoice left against a challan that somehow reads as open.
    existing = _active_invoice(db, challan.id)
    if existing is not None:
        raise already_invoiced_error(challan, existing)


def _require_same_version(challan: DeliveryChallan, seen: datetime | None) -> None:
    """Refuse a draft read before the challan last changed."""
    if seen is None:
        return
    # The column holds naive UTC; a caller may send the same instant with an offset.
    if seen.tzinfo is not None:
        seen = seen.astimezone(timezone.utc).replace(tzinfo=None)
    if seen != challan.updated_at:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "challan_changed",
                "message": (
                    f"{challan.challan_number} was changed after this conversion was opened. "
                    "Load the latest version and check it before saving."
                ),
            },
        )


def _fmt_rate(value: Decimal | float) -> str:
    return f"{float(value):.2f}".rstrip("0").rstrip(".")


def _draft_warnings(
    db: Session,
    challan: DeliveryChallan,
    products: dict[int, Product],
    company: CompanyProfile,
) -> list[ConversionWarning]:
    warnings: list[ConversionWarning] = []

    def warn(code: str, message: str) -> None:
        warnings.append(ConversionWarning(code=code, message=message))

    ledger = challan.ledger
    was_interstate = invoice_is_interstate(challan)
    company_gst = company.gst
    ledger_gst = ledger.gst if ledger else None
    is_interstate = invoice_is_interstate(SimpleNamespace(
        company_gst=company_gst,
        ledger_gst=ledger_gst,
        place_of_supply=(
            (challan.place_of_supply or default_place_of_supply(company_gst, ledger_gst))
            if (company_gst or "").strip()
            else None
        ),
    ))
    if was_interstate != is_interstate:
        old, new = ("IGST", "CGST + SGST") if was_interstate else ("CGST + SGST", "IGST")
        warn(
            "tax_split_changed",
            f"Tax will now be {new} instead of {old}, because a GSTIN has changed since this challan was "
            "written. The tax heads change; the total tax stays the same apart from rounding.",
        )

    for item in challan.items:
        product = products.get(item.product_id)
        if product is None:
            continue
        challan_rate = Decimal(str(item.gst_rate or 0))
        current_rate = Decimal(str(product.gst_rate or 0))
        if challan_rate != current_rate:
            warn(
                "rate_changed",
                f"GST on {product.name} was {_fmt_rate(challan_rate)}% on this challan and is now "
                f"{_fmt_rate(current_rate)}%. The invoice uses the current rate. The price is kept, "
                "so the total changes.",
            )
        if (item.hsn_sac or None) != (product.hsn_sac or None):
            warn(
                "hsn_changed",
                f"HSN/SAC of {product.name} is now {product.hsn_sac or 'not set'}. The invoice uses the current code.",
            )
        quantity = Decimal(str(item.quantity))
        if not product.allow_decimal and quantity != quantity.to_integral_value():
            warn(
                "quantity_not_whole",
                f"{product.name} is now sold in whole numbers, but this challan has {quantity.normalize():f}. "
                "Change the quantity before saving.",
            )

    if challan.shipping_address and not _usable_shipping_address_id(db, challan, company.id):
        warn(
            "shipping_address_gone",
            "The shipping address on this challan has since been deleted from the ledger. "
            "The invoice defaults to the billing address; choose another if needed.",
        )
    return warnings


def _products_by_id(db: Session, product_ids: set[int], company_id: int) -> dict[int, Product]:
    if not product_ids:
        return {}
    return {
        product.id: product
        for product in db.query(Product).filter(
            Product.id.in_(product_ids),
            company_scope(Product.company_id, company_id),
        )
    }


def build_conversion_draft(
    db: Session,
    challan: DeliveryChallan,
    *,
    company: CompanyProfile,
) -> DeliveryChallanConversionDraft:
    """What the composer opens with, and what to look at before saving. Reads only."""
    _require_convertible(db, challan)
    today = india_today()
    products = _products_by_id(db, {item.product_id for item in challan.items}, company.id)

    # By id, never by copying the snapshot into new_shipping_address: that field
    # always inserts a row, so each conversion would add a duplicate address.
    shipping_id = _usable_shipping_address_id(db, challan, company.id)
    invoice = DeliveryChallanConvert(
        challan_updated_at=challan.updated_at,
        ledger_id=challan.ledger_id,
        voucher_type="sales",
        invoice_date=today,
        place_of_supply=challan.place_of_supply,
        # No challan text here: the invoice PDF prints the challan number and date
        # from source_challan_id, so the user can't drop it and Duplicate can't copy it.
        reference_notes=None,
        tax_inclusive=False,
        apply_round_off=False,
        shipping_address_same_as_billing=shipping_id is None,
        shipping_address_id=shipping_id,
        items=[
            InvoiceItemCreate(
                product_id=item.product_id,
                quantity=float(item.quantity),
                unit_price=float(item.unit_price),
                description=item.description,
            )
            for item in challan.items
        ],
    )
    return DeliveryChallanConversionDraft(
        challan_id=challan.id,
        challan_number=challan.challan_number,
        challan_date=challan.challan_date,
        invoice=invoice,
        challan_items=[
            ChallanConversionLine(
                product_id=item.product_id,
                product_name=products[item.product_id].name if item.product_id in products else None,
                quantity=float(item.quantity),
            )
            for item in challan.items
        ],
        warnings=_draft_warnings(db, challan, products, company),
    )


def convert_challan(
    db: Session,
    challan_id: int,
    payload: DeliveryChallanConvert,
    *,
    created_by: int,
    company: CompanyProfile,
) -> tuple[DeliveryChallan, Invoice, list[str]]:
    """Create the invoice and mark the challan invoiced, in the caller's one transaction.

    The challan's hold on stock is released first, so the invoice's own availability
    check and sale see it: the net effect is the invoice's quantities, whatever they
    are. The row lock serialises two conversions of one challan; the partial unique
    index on ``invoices.source_challan_id`` is the backstop.
    """
    if payload.voucher_type != "sales":
        raise HTTPException(status_code=400, detail="A delivery challan can only convert to a sales invoice")

    challan = require_challan(db, company.id, challan_id, lock=True)
    _require_convertible(db, challan)
    _require_same_version(challan, payload.challan_updated_at)

    _release(db, challan, context=f"invoicing delivery challan {challan.challan_number}")
    invoice, warnings = create_invoice_record(
        db,
        payload,
        created_by=created_by,
        company=company,
        active_fy=get_active_fy(db, company_id=company.id),
    )
    invoice.source_challan_id = challan.id
    challan.status = STATUS_INVOICED
    challan.invoiced_at = datetime.utcnow()
    challan.updated_at = challan.invoiced_at
    return challan, invoice, warnings


# ---------------------------------------------------------------------------
# Hooks for the invoice routes
# ---------------------------------------------------------------------------

def lock_source_challan(db: Session, invoice: Invoice) -> DeliveryChallan | None:
    """Lock the challan an invoice was made from, before anything else is locked."""
    if invoice.source_challan_id is None:
        return None
    return (
        db.query(DeliveryChallan)
        .filter(
            DeliveryChallan.id == invoice.source_challan_id,
            DeliveryChallan.company_id == invoice.company_id,
        )
        .populate_existing()
        .with_for_update()
        .first()
    )


def reopen_challan_after_invoice_cancelled(db: Session, challan: DeliveryChallan | None) -> None:
    """The invoice is gone, so the challan's goods are out on it again: back to open, -C.

    Runs after the invoice's own stock has come back (+I), so the shortfall it can
    raise is only when that stock has since been sold elsewhere.
    """
    if challan is None or challan.status != STATUS_INVOICED:
        return
    challan.status = STATUS_OPEN
    challan.invoiced_at = None
    challan.updated_at = datetime.utcnow()
    _take_out(
        db,
        challan,
        document=f"re-opening delivery challan {challan.challan_number}",
        context=f"re-opening delivery challan {challan.challan_number}",
    )


def require_challan_restorable(db: Session, challan: DeliveryChallan | None, invoice: Invoice) -> None:
    """Refuse to restore an invoice whose challan has since been invoiced again."""
    if challan is None:
        return
    newer = _active_invoice(db, challan.id, excluding=invoice.id)
    if newer is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "challan_reinvoiced",
                "message": (
                    f"{challan.challan_number} was invoiced again as {newer.invoice_number}. "
                    "Cancel that invoice first."
                ),
                "invoice_id": newer.id,
                "invoice_number": newer.invoice_number,
            },
        )


def close_challan_after_invoice_restored(db: Session, challan: DeliveryChallan | None) -> None:
    """The invoice is live again, so the challan is invoiced again and releases its hold.

    Runs before the invoice's own stock is taken. A challan cancelled in the meantime
    stays cancelled and holds nothing; the restored invoice then stands on its own.
    """
    if challan is None or challan.status != STATUS_OPEN:
        return
    _release(db, challan, context=f"invoicing delivery challan {challan.challan_number}")
    challan.status = STATUS_INVOICED
    challan.invoiced_at = datetime.utcnow()
    challan.updated_at = challan.invoiced_at


def challan_age_days(challan: DeliveryChallan, today: date | None = None) -> int | None:
    """Days since the challan date while open; None once invoiced or cancelled."""
    if challan.status != STATUS_OPEN or challan.challan_date is None:
        return None
    return max(0, ((today or india_today()) - challan.challan_date).days)
