"""Sales analytics report builders.

The JSON and CSV routes both call these builders so the two can never disagree
about a number — the same split :mod:`src.api.routes.ledgers` uses for the day
book.

Month bucketing happens in Python rather than via ``date_trunc``: the test suite
runs on SQLite while production runs on Postgres, and the dashboard already set
this precedent.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from itertools import groupby
from operator import attrgetter

from sqlalchemy import func
from sqlalchemy.engine import Row
from sqlalchemy.orm import Session, lazyload, load_only, selectinload

from src.models.buyer import Buyer
from src.models.credit_note import CreditNote, CreditNoteItem
from src.models.inventory import Inventory
from src.models.invoice import Invoice, InvoiceItem
from src.models.product import Product
from src.services.gst_tax_service import money as _money
from src.services.invoice_discounts import (
    DiscountedLine,
    apportion_invoice_discount,
    build_invoice_discount_totals,
    discounted_line_amounts,
    invoice_discount_amount,
)

MONTHS_IN_TREND = 12
_MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def month_window(today: date, months: int = MONTHS_IN_TREND) -> list[tuple[int, int]]:
    """Return (year, month) tuples for the trailing ``months`` months, oldest first."""
    window: list[tuple[int, int]] = []
    year, month = today.year, today.month
    for _ in range(months):
        window.append((year, month))
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    return list(reversed(window))


def month_label(year: int, month: int) -> str:
    """Format a month as "Apr 26". Shared with the dashboard so labels match."""
    return f"{_MONTH_LABELS[month - 1]} {year % 100:02d}"


def months_between(from_date: date, to_date: date) -> list[tuple[int, int]]:
    """Every (year, month) touched by the range, inclusive, oldest first."""
    window: list[tuple[int, int]] = []
    year, month = from_date.year, from_date.month
    while (year, month) <= (to_date.year, to_date.month):
        window.append((year, month))
        month += 1
        if month == 13:
            month = 1
            year += 1
    return window


@dataclass
class MonthlyBucket:
    invoice_count: int = 0
    total_sales: Decimal = Decimal("0")
    taxable_value: Decimal = Decimal("0")
    gst_collected: Decimal = Decimal("0")
    discount_given: Decimal = Decimal("0")


@dataclass
class MonthlySalesData:
    rows: list[tuple[int, int, MonthlyBucket]]
    totals: MonthlyBucket


@dataclass
class ProductSalesData:
    rows: list[dict]
    totals: dict


def _date_bounds(from_date: date, to_date: date) -> tuple[datetime, datetime]:
    """Convert a date range to datetime bounds covering the whole end day.

    ``Invoice.invoice_date`` is a DateTime; comparing it against a bare date
    silently drops invoices dated on ``to_date`` that carry a time component.
    """
    return datetime.combine(from_date, time.min), datetime.combine(to_date, time.max)


def _scoped_invoice_query(
    db: Session,
    *,
    company_id: int,
    voucher_type: str,
    from_date: date,
    to_date: date,
    ledger_id: int | None = None,
):
    start, end = _date_bounds(from_date, to_date)
    # Strict company_id equality (not the NULL-tolerant form used by
    # invoice_payments for legacy rows): on a reporting surface a NULL-company
    # invoice would leak into every company's revenue. Legacy rows were
    # populated by migration 20260424000002_backfill_company_scope_data.
    query = db.query(Invoice).filter(
        Invoice.company_id == company_id,
        Invoice.status == "active",
        Invoice.voucher_type == voucher_type,
        Invoice.invoice_date >= start,
        Invoice.invoice_date <= end,
    )
    if ledger_id is not None:
        query = query.filter(Invoice.ledger_id == ledger_id)
    return query


def _billed_invoices(
    db: Session,
    *,
    company_id: int,
    voucher_type: str,
    from_date: date,
    to_date: date,
    ledger_id: int | None = None,
    product_id: int | None = None,
) -> list[tuple[Invoice, dict[int, DiscountedLine]]]:
    """In-scope invoices, each with what every one of its lines billed, keyed by item id.

    A line's figures are :func:`discounted_line_amounts` with ``include_round_off``:
    its taxable value and GST after its share of the invoice-level discount and the
    round-off. That is exactly what a credit note credits for the line, so a report
    that books these and takes active notes off nets a fully returned invoice to
    zero, however it was discounted or rounded (#790). TCS is never part of a line.

    Under a product filter the invoice set narrows to invoices carrying that product,
    but every line is still loaded: the discount and round-off are shared over all
    of an invoice's lines, so the filtered product only ever takes its own share.

    A line from before the tax columns carries only its total, which stands in as
    its taxable value, as credit notes do.

    Only the columns the split needs are loaded: a full ``Invoice`` row carries the
    company logo snapshot, far too heavy to load per invoice here.
    """
    query = _scoped_invoice_query(
        db,
        company_id=company_id,
        voucher_type=voucher_type,
        from_date=from_date,
        to_date=to_date,
        ledger_id=ledger_id,
    ).options(
        load_only(
            Invoice.id, Invoice.invoice_date, Invoice.ledger_id, Invoice.ledger_name,
            Invoice.tax_inclusive, Invoice.taxable_amount, Invoice.total_tax_amount,
            Invoice.round_off_amount, Invoice.tcs_amount, Invoice.total_amount,
            Invoice.company_gst, Invoice.ledger_gst, Invoice.place_of_supply,
        ),
        lazyload("*"),
        selectinload(Invoice.items).load_only(
            InvoiceItem.id, InvoiceItem.invoice_id, InvoiceItem.product_id, InvoiceItem.quantity,
            InvoiceItem.taxable_amount, InvoiceItem.tax_amount, InvoiceItem.line_total,
        ),
    )
    if product_id is not None:
        query = query.filter(Invoice.items.any(InvoiceItem.product_id == product_id))

    billed_invoices: list[tuple[Invoice, dict[int, DiscountedLine]]] = []
    for invoice in query.order_by(Invoice.id).all():
        billed = discounted_line_amounts(invoice, include_round_off=True)
        for item in invoice.items:
            if not item.taxable_amount and not item.tax_amount:
                billed[item.id] = DiscountedLine(_money(Decimal(str(item.line_total or 0))), Decimal("0"))
        billed_invoices.append((invoice, billed))
    return billed_invoices


def _billed_invoice_lines(
    db: Session,
    *,
    company_id: int,
    voucher_type: str,
    from_date: date,
    to_date: date,
    ledger_id: int | None,
    product_id: int | None,
) -> list[tuple[Invoice, InvoiceItem, DiscountedLine]]:
    """``(invoice, line, what the line billed)`` for every in-scope line.

    See :func:`_billed_invoices`. Under a product filter only that product's lines
    are returned, after the discount has been shared over all of their invoice's lines.
    """
    lines: list[tuple[Invoice, InvoiceItem, DiscountedLine]] = []
    for invoice, billed in _billed_invoices(
        db, company_id=company_id, voucher_type=voucher_type, from_date=from_date,
        to_date=to_date, ledger_id=ledger_id, product_id=product_id,
    ):
        for item in invoice.items:
            if product_id is None or item.product_id == product_id:
                lines.append((invoice, item, billed[item.id]))
    return lines


def _active_note_lines(
    db: Session,
    *,
    company_id: int,
    voucher_type: str,
    from_date: date,
    to_date: date,
    ledger_id: int | None,
    product_id: int | None,
):
    """Active note lines in the period that run against this report's voucher type.

    Outward notes reverse sales, inward (supplier) notes reverse purchases; a NULL
    direction predates the column and was always outward.
    """
    expected = "outward" if voucher_type == "sales" else "inward"
    return [
        note
        for note in _credit_note_lines(
            db, company_id=company_id, from_date=from_date, to_date=to_date,
            ledger_id=ledger_id, product_id=product_id,
        )
        if (note.direction or "outward") == expected
    ]


def build_monthly_sales_report(
    db: Session,
    *,
    company_id: int,
    voucher_type: str,
    from_date: date,
    to_date: date,
    ledger_id: int | None = None,
) -> MonthlySalesData:
    """Aggregate invoices into one row per calendar month in the range.

    Every month in the range is emitted, including empty ones — a chart with
    gaps silently omitted would misrepresent a quiet month as no month.

    Taxable value and GST are what the invoice's lines billed after the
    invoice-level discount and round-off (see :func:`_billed_invoices`), so with
    TCS they add up to total sales; the discount is still reported on its own as
    ``discount_given``.

    Active credit notes (outward for sales, inward for purchases) reduce taxable
    value, GST and total sales, TCS included, in the month of the *credit note*
    date. A fully returned invoice nets to zero.
    """
    billed_invoices = _billed_invoices(
        db,
        company_id=company_id,
        voucher_type=voucher_type,
        from_date=from_date,
        to_date=to_date,
        ledger_id=ledger_id,
    )

    discounts = build_invoice_discount_totals(db, [invoice for invoice, _ in billed_invoices])

    buckets: dict[tuple[int, int], MonthlyBucket] = {
        key: MonthlyBucket() for key in months_between(from_date, to_date)
    }

    for invoice, billed in billed_invoices:
        key = (invoice.invoice_date.year, invoice.invoice_date.month)
        bucket = buckets.get(key)
        if bucket is None:
            # Defensive: the query is already bounded to the range.
            continue
        bucket.invoice_count += 1
        bucket.total_sales += Decimal(str(invoice.total_amount or 0))
        bucket.taxable_value += sum((line.taxable_amount for line in billed.values()), Decimal("0"))
        bucket.gst_collected += sum((line.tax_amount for line in billed.values()), Decimal("0"))
        bucket.discount_given += discounts[invoice.id].total_discount

    # Notes reduce the month they were issued in, not the month of the invoice
    # they reverse — the same split the day book uses. Every note type (return,
    # discount, adjustment) reduces value here: there is no per-unit figure in
    # this report for the return/other distinction to matter.
    for note in _active_note_lines(
        db, company_id=company_id, voucher_type=voucher_type, from_date=from_date,
        to_date=to_date, ledger_id=ledger_id, product_id=None,
    ):
        bucket = buckets.get((note.credit_note_date.year, note.credit_note_date.month))
        if bucket is None:
            continue
        taxable_value = Decimal(str(note.taxable_amount or 0))
        tax_value = Decimal(str(note.tax_amount or 0))
        bucket.taxable_value -= taxable_value
        bucket.gst_collected -= tax_value
        bucket.total_sales -= taxable_value + tax_value + Decimal(str(note.tcs_amount or 0))

    totals = MonthlyBucket()
    for bucket in buckets.values():
        totals.invoice_count += bucket.invoice_count
        totals.total_sales += bucket.total_sales
        totals.taxable_value += bucket.taxable_value
        totals.gst_collected += bucket.gst_collected
        totals.discount_given += bucket.discount_given

    rows = [(year, month, buckets[(year, month)]) for year, month in months_between(from_date, to_date)]
    return MonthlySalesData(rows=rows, totals=totals)


def average_of(total: Decimal, count) -> Decimal:
    """Mean guarded against a zero denominator (empty months, zero-qty lines)."""
    if not count:
        return Decimal("0.00")
    return _money(total / Decimal(str(count)))


def build_product_sales_report(
    db: Session,
    *,
    company_id: int,
    voucher_type: str,
    from_date: date,
    to_date: date,
    ledger_id: int | None = None,
    product_id: int | None = None,
    sort_by: str = "revenue",
    sort_dir: str = "desc",
    limit: int | None = None,
) -> ProductSalesData:
    """Aggregate invoice lines into one row per product.

    Each line counts for what it billed after the invoice-level discount and
    round-off (see :func:`_billed_invoices`): ex-GST as ``sales_amount``, its GST
    as ``total_gst``, both together as ``total_revenue``.

    Active credit notes dated in the range (outward for sales, inward for
    purchases) then reduce ``quantity_sold`` (return notes only) and all three
    money figures (every note type), the rule Product Performance uses, so a
    fully returned invoice nets to zero. A product with notes but no invoice in
    the range still gets a row, as it does in Profit & Loss and Sales by Month.
    The average selling price is over the gross, pre-note figures.
    """
    acc: dict[int, dict] = {}

    def bucket(pid: int) -> dict:
        if pid not in acc:
            acc[pid] = {
                "gross_qty": Decimal("0"),
                "gross_taxable": Decimal("0"),
                "qty": Decimal("0"),
                "taxable": Decimal("0"),
                "tax": Decimal("0"),
                "invoice_ids": set(),
            }
        return acc[pid]

    for invoice, item, billed in _billed_invoice_lines(
        db, company_id=company_id, voucher_type=voucher_type, from_date=from_date,
        to_date=to_date, ledger_id=ledger_id, product_id=product_id,
    ):
        entry = bucket(item.product_id)
        qty = Decimal(str(item.quantity or 0))
        entry["gross_qty"] += qty
        entry["gross_taxable"] += billed.taxable_amount
        entry["qty"] += qty
        entry["taxable"] += billed.taxable_amount
        entry["tax"] += billed.tax_amount
        # A set: a product on two lines of one invoice counts that invoice once.
        entry["invoice_ids"].add(invoice.id)

    for note in _active_note_lines(
        db, company_id=company_id, voucher_type=voucher_type, from_date=from_date,
        to_date=to_date, ledger_id=ledger_id, product_id=product_id,
    ):
        entry = bucket(note.product_id)
        entry["taxable"] -= Decimal(str(note.taxable_amount or 0))
        entry["tax"] -= Decimal(str(note.tax_amount or 0))
        if note.credit_note_type == "return":
            entry["qty"] -= Decimal(str(note.quantity or 0))

    products = {}
    stock_map: dict[int, Decimal] = {}
    if acc:
        products = {
            product.id: product
            for product in db.query(Product.id, Product.name, Product.sku, Product.maintain_inventory)
            .filter(Product.id.in_(list(acc)))
            .all()
        }
        # Stock is fetched separately rather than outer-joined: a product with
        # maintain_inventory=False has no meaningful stock, and a join would
        # report a misleading 0 instead of "not tracked".
        stock_map = {
            pid: Decimal(str(qty or 0))
            for pid, qty in db.query(Inventory.product_id, Inventory.quantity)
            .filter(Inventory.company_id == company_id, Inventory.product_id.in_(list(acc)))
            .all()
        }

    rows: list[dict] = []
    for pid, entry in acc.items():
        product = products.get(pid)
        if product is None:  # defensive: a line pointing at a deleted product
            continue
        rows.append({
            "product_id": pid,
            "name": product.name,
            "sku": product.sku,
            "quantity_sold": entry["qty"],
            "sales_amount": _money(entry["taxable"]),
            "average_selling_price": average_of(entry["gross_taxable"], entry["gross_qty"]),
            "total_revenue": _money(entry["taxable"] + entry["tax"]),
            "total_gst": _money(entry["tax"]),
            "invoice_count": len(entry["invoice_ids"]),
            "current_stock": stock_map.get(pid, Decimal("0")) if product.maintain_inventory else None,
        })

    _sort_rows(rows, sort_by=sort_by, sort_dir=sort_dir)

    if limit is not None:
        rows = rows[:limit]

    totals = {
        "product_count": len(rows),
        "quantity_sold": sum((row["quantity_sold"] for row in rows), Decimal("0")),
        "sales_amount": sum((row["sales_amount"] for row in rows), Decimal("0")),
        "total_revenue": sum((row["total_revenue"] for row in rows), Decimal("0")),
        "total_gst": sum((row["total_gst"] for row in rows), Decimal("0")),
        "invoice_count": _distinct_invoice_count(
            db,
            company_id=company_id,
            voucher_type=voucher_type,
            from_date=from_date,
            to_date=to_date,
            ledger_id=ledger_id,
            product_ids=[row["product_id"] for row in rows],
        ),
    }

    return ProductSalesData(rows=rows, totals=totals)


def _sort_rows(rows: list[dict], *, sort_by: str, sort_dir: str) -> None:
    reverse = sort_dir == "desc"

    if sort_by == "stock":
        # Stock isn't in the grouped query, so this can't be pushed into SQL.
        # Untracked products (None) sort last in both directions rather than
        # being treated as zero.
        tracked = [row for row in rows if row["current_stock"] is not None]
        untracked = [row for row in rows if row["current_stock"] is None]
        tracked.sort(key=lambda row: row["current_stock"], reverse=reverse)
        rows[:] = tracked + untracked
        return

    keys = {
        "quantity": lambda row: row["quantity_sold"],
        "revenue": lambda row: row["total_revenue"],
        "name": lambda row: (row["name"] or "").lower(),
    }
    rows.sort(key=keys[sort_by], reverse=reverse)


def _margin_pct(gross_profit: Decimal, revenue: Decimal) -> Decimal:
    """Gross margin as a percentage, guarded against zero revenue."""
    if not revenue:
        return Decimal("0.00")
    return _money(gross_profit / revenue * Decimal("100"))


@dataclass
class ProfitLossData:
    product_rows: list[dict]
    monthly_rows: list[tuple[int, int, dict]]
    customer_rows: list[dict]
    totals: dict


def apportioned_invoice_rows(query, *, gst_inclusive=False):
    """Yield ``(row, share of the invoice discount)`` for every invoice line.

    Every row must carry the invoice header totals under the names
    :func:`invoice_discount_amount` reads (``taxable_amount``,
    ``total_tax_amount``, ``tcs_amount``, ``round_off_amount``,
    ``total_amount``), the invoice
    id as ``row.id``, and the line's weight: ``line_taxable``, or ``line_total``
    with ``gst_inclusive``. Rows are grouped by invoice in
    ``Invoice.id, InvoiceItem.id`` order and the discount is apportioned
    across *all* of an invoice's lines before the caller filters any out, so
    a filtered product never takes the whole discount.

    By default each share is the ex-GST part of the discount, to take off
    ``line_taxable``. With ``gst_inclusive`` it is the line's share of the whole
    discount, to take off ``line_total``, which already includes the GST.
    """
    rows = query.order_by(Invoice.id, InvoiceItem.id).yield_per(1000)
    for _, invoice_group in groupby(rows, key=attrgetter("id")):
        invoice_rows = list(invoice_group)
        header = invoice_rows[0]  # every row repeats the invoice's own columns
        weights = [
            Decimal(str((row.line_total if gst_inclusive else row.line_taxable) or 0))
            for row in invoice_rows
        ]
        shares = apportion_invoice_discount(
            weights,
            # invoice_discount_amount only reads the five total columns, all
            # of which the row carries under the same names.
            invoice_discount=invoice_discount_amount(header),
            invoice_tax=Decimal("0") if gst_inclusive else Decimal(str(header.total_tax_amount or 0)),
        )
        yield from zip(invoice_rows, shares)


def build_profit_loss_report(
    db: Session,
    *,
    company_id: int,
    voucher_type: str,
    from_date: date,
    to_date: date,
    ledger_id: int | None = None,
    product_id: int | None = None,
) -> ProfitLossData:
    """Profit & loss per product, per month, and per customer.

    Cost basis is the product's *current* ``purchase_price`` — invoice lines
    carry no cost snapshot, so a historical period is priced at today's cost and
    its margin shifts if the cost is later edited. Revenue is what each line
    billed ex-GST, after its share of the invoice-level discount and round-off
    (see :func:`_billed_invoices`); GST is pass-through and never counted as
    profit.

    Active credit notes dated in the range then reduce quantity, revenue and
    COGS the way Product Performance does: every note type lowers revenue, but
    only a ``return`` note lowers quantity and COGS, since a discount or
    adjustment note sends no goods back. A fully returned invoice nets to zero.

    All three breakdowns come from one line-level scan so the numbers can't
    diverge. When ``product_id`` is set, ``monthly_rows`` narrows to that
    product's series — the per-product purchase-vs-sales view reuses it directly.
    """
    lines = _billed_invoice_lines(
        db, company_id=company_id, voucher_type=voucher_type, from_date=from_date,
        to_date=to_date, ledger_id=ledger_id, product_id=product_id,
    )
    # Notes are booked in the month of the *credit note* date, not the invoice's.
    note_lines = _active_note_lines(
        db, company_id=company_id, voucher_type=voucher_type, from_date=from_date,
        to_date=to_date, ledger_id=ledger_id, product_id=product_id,
    )

    # Every product a line or a note touches. A note's product (or customer) may
    # have no invoice in the range, e.g. when the invoice falls before a narrower
    # window than the note.
    product_ids = {item.product_id for _, item, _ in lines} | {note.product_id for note in note_lines}
    catalogue = {
        product.id: product
        for product in db.query(Product.id, Product.name, Product.sku, Product.purchase_price)
        .filter(Product.id.in_(product_ids))
        .all()
    } if product_ids else {}

    # Per-product, per-month, and per-customer accumulators, all built in one pass.
    products: dict[int, dict] = {}
    months: dict[tuple[int, int], dict] = {
        key: {"quantity": Decimal("0"), "revenue": Decimal("0"), "cogs": Decimal("0")}
        for key in months_between(from_date, to_date)
    }
    customers: dict[int | None, dict] = {}

    def product_entry(pid: int) -> dict | None:
        if pid not in products and pid in catalogue:
            info = catalogue[pid]
            products[pid] = {
                "product_id": pid,
                "name": info.name,
                "sku": info.sku,
                "purchase_price": Decimal(str(info.purchase_price or 0)),
                "quantity_sold": Decimal("0"),
                "revenue": Decimal("0"),
            }
        return products.get(pid)

    def customer_entry(ledger: int | None, name: str | None) -> dict:
        if ledger not in customers:
            customers[ledger] = {
                "ledger_id": ledger,
                "name": name or "—",
                "revenue": Decimal("0"),
                "cogs": Decimal("0"),
                "invoice_ids": set(),
            }
        return customers[ledger]

    def book(product: dict, when: datetime, customer: dict, units: Decimal, revenue: Decimal) -> None:
        """Add one line (or, with negative figures, take one note line off)."""
        line_cogs = units * product["purchase_price"]
        product["quantity_sold"] += units
        product["revenue"] += revenue
        bucket = months.get((when.year, when.month))
        if bucket is not None:  # defensive: the queries are already range-bounded
            bucket["quantity"] += units
            bucket["revenue"] += revenue
            bucket["cogs"] += line_cogs
        customer["revenue"] += revenue
        customer["cogs"] += line_cogs

    for invoice, item, billed in lines:
        product = product_entry(item.product_id)
        if product is None:  # defensive: a line pointing at a deleted product
            continue
        customer = customer_entry(invoice.ledger_id, invoice.ledger_name)
        customer["invoice_ids"].add(invoice.id)
        book(product, invoice.invoice_date, customer, Decimal(str(item.quantity or 0)), billed.taxable_amount)

    missing_ledger_ids = {note.ledger_id for note in note_lines} - customers.keys()
    ledger_names: dict[int, str] = {}
    if missing_ledger_ids:
        ledger_names = dict(db.query(Buyer.id, Buyer.name).filter(Buyer.id.in_(missing_ledger_ids)).all())

    for note in note_lines:
        product = product_entry(note.product_id)
        if product is None:
            continue
        units = Decimal(str(note.quantity or 0)) if note.credit_note_type == "return" else Decimal("0")
        customer = customer_entry(note.ledger_id, ledger_names.get(note.ledger_id))
        book(product, note.credit_note_date, customer, -units, -Decimal(str(note.taxable_amount or 0)))

    product_rows: list[dict] = []
    for product in products.values():
        revenue = _money(product["revenue"])
        cogs = _money(product["quantity_sold"] * product["purchase_price"])
        gross_profit = _money(revenue - cogs)
        product_rows.append({
            "product_id": product["product_id"],
            "name": product["name"],
            "sku": product["sku"],
            "quantity_sold": product["quantity_sold"],
            "sales_amount": revenue,
            "average_selling_price": average_of(revenue, product["quantity_sold"]),
            "purchase_price": _money(product["purchase_price"]),
            "cogs": cogs,
            "gross_profit": gross_profit,
            "margin_pct": _margin_pct(gross_profit, revenue),
        })
    # Most profitable first — the table opens on what matters and the chart's
    # Top-N slice is a straight prefix.
    product_rows.sort(key=lambda row: row["gross_profit"], reverse=True)

    monthly_rows: list[tuple[int, int, dict]] = []
    for year, month in months_between(from_date, to_date):
        bucket = months[(year, month)]
        revenue = _money(bucket["revenue"])
        cogs = _money(bucket["cogs"])
        gross_profit = _money(revenue - cogs)
        monthly_rows.append((year, month, {
            "quantity": bucket["quantity"],
            "revenue": revenue,
            "cogs": cogs,
            "gross_profit": gross_profit,
            "margin_pct": _margin_pct(gross_profit, revenue),
        }))

    customer_rows: list[dict] = []
    for customer in customers.values():
        revenue = _money(customer["revenue"])
        cogs = _money(customer["cogs"])
        gross_profit = _money(revenue - cogs)
        customer_rows.append({
            "ledger_id": customer["ledger_id"],
            "name": customer["name"],
            "revenue": revenue,
            "cogs": cogs,
            "gross_profit": gross_profit,
            "margin_pct": _margin_pct(gross_profit, revenue),
            "invoice_count": len(customer["invoice_ids"]),
        })
    customer_rows.sort(key=lambda row: row["gross_profit"], reverse=True)

    total_revenue = sum((row["sales_amount"] for row in product_rows), Decimal("0"))
    total_cogs = sum((row["cogs"] for row in product_rows), Decimal("0"))
    total_gross_profit = _money(total_revenue - total_cogs)
    totals = {
        "product_count": len(product_rows),
        "quantity_sold": sum((row["quantity_sold"] for row in product_rows), Decimal("0")),
        "revenue": _money(total_revenue),
        "cogs": _money(total_cogs),
        "gross_profit": total_gross_profit,
        "margin_pct": _margin_pct(total_gross_profit, total_revenue),
    }

    return ProfitLossData(
        product_rows=product_rows,
        monthly_rows=monthly_rows,
        customer_rows=customer_rows,
        totals=totals,
    )


# --- Product performance ----------------------------------------------------

PRODUCT_PERFORMANCE_SORTS = (
    "name",
    "units_sold",
    "units_returned",
    "net_units_sold",
    "units_bought",
    "net_units_bought",
    "average_selling_price",
    "average_buying_price",
    "revenue",
    "purchase_spend",
    "cogs",
    "gross_profit",
    "margin_pct",
    "profit_per_unit",
    "current_stock",
)

COST_BASIS_PURCHASES = "purchases"
COST_BASIS_CURRENT_PRICE = "current_price"

_DatedInvoiceLine = tuple[int, Decimal, Decimal, datetime, int]
# A row of :func:`_credit_note_lines`, read by attribute (direction, credit_note_type,
# ledger_id, product_id, quantity, taxable_amount, tax_amount, tcs_amount,
# credit_note_date, invoice_id).
_CreditNoteLine = Row


@dataclass
class ProductPerformanceData:
    rows: list[dict]
    totals: dict


def _ratio(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    """Rounded ``numerator / denominator``; None (not 0) when undefined."""
    if not denominator:
        return None
    return _money(numerator / denominator)


def _discounted_invoice_lines(
    db: Session,
    *,
    company_id: int,
    voucher_type: str,
    from_date: date,
    to_date: date,
    ledger_id: int | None,
    product_id: int | None,
) -> list[tuple[int, Decimal, Decimal]]:
    """``(product_id, quantity, taxable net of invoice discount)`` per line.

    The undated form of :func:`_dated_discounted_invoice_lines`, which the
    period report needs.
    """
    return [
        (pid, qty, taxable)
        for pid, qty, taxable, _when, _invoice_id in _dated_discounted_invoice_lines(
            db, company_id=company_id, voucher_type=voucher_type, from_date=from_date,
            to_date=to_date, ledger_id=ledger_id, product_id=product_id,
        )
    ]


def _dated_discounted_invoice_lines(
    db: Session,
    *,
    company_id: int,
    voucher_type: str,
    from_date: date,
    to_date: date,
    ledger_id: int | None,
    product_id: int | None,
) -> list[_DatedInvoiceLine]:
    """``(product_id, quantity, taxable the line billed, invoice_date, invoice_id)``.

    The taxable value is after the line's share of the invoice-level discount
    and round-off, the same figure a credit note credits; see
    :func:`_billed_invoices`, which also covers the product filter.
    """
    return [
        (
            item.product_id, Decimal(str(item.quantity or 0)), billed.taxable_amount,
            invoice.invoice_date, invoice.id,
        )
        for invoice, item, billed in _billed_invoice_lines(
            db, company_id=company_id, voucher_type=voucher_type, from_date=from_date,
            to_date=to_date, ledger_id=ledger_id, product_id=product_id,
        )
    ]


def _credit_note_lines(
    db: Session,
    *,
    company_id: int,
    from_date: date,
    to_date: date,
    ledger_id: int | None,
    product_id: int | None,
) -> list[_CreditNoteLine]:
    """Active credit/debit note lines in the period, dated by ``credit_note_date``.

    Strict company equality on the note header: unlike
    :mod:`src.services.credit_note_reporting`, a NULL-company note must not
    leak into every company's figures on a reporting surface.

    Rows carry ``tax_amount``, ``tcs_amount`` and ``ledger_id`` alongside the
    fields Product Performance uses, so the other report builders can reduce
    GST-inclusive totals, total sales and per-customer figures with the same query.
    """
    start, end = _date_bounds(from_date, to_date)
    query = (
        db.query(
            CreditNote.direction,
            CreditNote.credit_note_type,
            CreditNote.ledger_id,
            CreditNoteItem.product_id,
            CreditNoteItem.quantity,
            CreditNoteItem.taxable_amount,
            CreditNoteItem.tax_amount,
            CreditNoteItem.tcs_amount,
            CreditNote.credit_note_date,
            CreditNoteItem.invoice_id,
        )
        .join(CreditNote, CreditNoteItem.credit_note_id == CreditNote.id)
        .filter(
            CreditNote.company_id == company_id,
            CreditNote.status == "active",
            CreditNote.credit_note_date >= start,
            CreditNote.credit_note_date <= end,
            CreditNoteItem.product_id.isnot(None),
        )
    )
    if ledger_id is not None:
        query = query.filter(CreditNote.ledger_id == ledger_id)
    if product_id is not None:
        query = query.filter(CreditNoteItem.product_id == product_id)
    return query.all()


def _net_purchase_lines(
    lines: Iterable[_DatedInvoiceLine], note_lines: Iterable[_CreditNoteLine],
) -> list[_DatedInvoiceLine]:
    """Net supplier notes against their in-period purchase and its original month.

    Cash-flow figures still book every note on its note date. The cost of this
    period's purchases must not absorb a refund against an earlier purchase.
    """
    net = list(lines)
    purchase_dates = {(invoice_id, pid): when for pid, _qty, _taxable, when, invoice_id in net}
    for note in note_lines:
        pid, invoice_id = note.product_id, note.invoice_id
        when = purchase_dates.get((invoice_id, pid))
        if note.direction == "inward" and invoice_id is not None and when is not None:
            net.append((
                pid,
                -Decimal(str(note.quantity or 0)) if note.credit_note_type == "return" else Decimal("0"),
                -Decimal(str(note.taxable_amount or 0)),
                when,
                invoice_id,
            ))
    return net


def _purchase_unit_costs(lines: Iterable[_DatedInvoiceLine]) -> dict[int, Decimal]:
    """Weighted average ex-GST unit cost, net of supplier credit/debit notes.

    Kept unrounded: it is multiplied by unit counts for COGS, and rounding the
    unit cost first would scale a sub-paisa error by the quantity.
    """
    spend: dict[int, Decimal] = {}
    units: dict[int, Decimal] = {}
    for pid, qty, taxable, _when, _invoice_id in lines:
        spend[pid] = spend.get(pid, Decimal("0")) + taxable
        units[pid] = units.get(pid, Decimal("0")) + qty
    # Fully returned purchases intentionally fall back to the current price.
    # A genuine full discount can still leave units with a known zero cost.
    return {pid: spend[pid] / units[pid] for pid in spend if units[pid] > 0 and spend[pid] >= 0}


# The raw sums every product (or month) accumulates before figures are derived.
_PERFORMANCE_FIELDS = (
    "units_sold", "units_returned", "units_bought", "units_purchase_returned",
    "sales_value", "return_value", "purchase_value", "purchase_return_value",
)


def _empty_performance_bucket() -> dict[str, Decimal]:
    return {field: Decimal("0") for field in _PERFORMANCE_FIELDS}


def _add_note_line(entry: dict[str, Decimal], direction, note_type, qty, taxable) -> None:
    """Fold one credit/debit note line into a bucket.

    Every note type reduces value; only ``return`` notes move units.
    """
    units = Decimal(str(qty or 0)) if note_type == "return" else Decimal("0")
    value = Decimal(str(taxable or 0))
    # A NULL direction predates the column; every such note was outward.
    if direction == "inward":
        entry["units_purchase_returned"] += units
        entry["purchase_return_value"] += value
    else:
        entry["units_returned"] += units
        entry["return_value"] += value


def _unit_cost(period_cost: Decimal | None, purchase_price) -> tuple[Decimal | None, str | None]:
    """The unit cost COGS is taken at, and where it came from.

    The period's weighted average purchase price wins; failing that the
    product's current ``purchase_price``; failing both, no cost at all.
    """
    if period_cost is not None:
        return period_cost, COST_BASIS_PURCHASES
    current = Decimal(str(purchase_price or 0))
    return (current, COST_BASIS_CURRENT_PRICE) if current > 0 else (None, None)


def _performance_figures(entry: dict[str, Decimal], unit_cost: Decimal | None, *, cogs: Decimal | None = None) -> dict:
    """Derive the reported figures from one bucket of raw sums.

    Shared by the per-product rows and the per-month series so a month can
    never be computed under different rules from the period it belongs to.
    ``cogs`` overrides ``net_units_sold x unit_cost`` for callers that need to
    control its rounding (see :func:`build_product_performance_detail`).
    """
    net_units_sold = entry["units_sold"] - entry["units_returned"]
    net_units_bought = entry["units_bought"] - entry["units_purchase_returned"]
    sales_value = _money(entry["sales_value"])
    return_value = _money(entry["return_value"])
    revenue = _money(sales_value - return_value)
    purchase_value = _money(entry["purchase_value"])
    purchase_return_value = _money(entry["purchase_return_value"])

    gross_profit = margin_pct = profit_per_unit = None
    if unit_cost is not None:
        if cogs is None:
            cogs = _money(net_units_sold * unit_cost)
        gross_profit = _money(revenue - cogs)
        margin_pct = _ratio(gross_profit * 100, revenue)
        profit_per_unit = _ratio(gross_profit, net_units_sold)
    else:
        cogs = None

    return {
        "units_sold": entry["units_sold"],
        "units_returned": entry["units_returned"],
        "net_units_sold": net_units_sold,
        "units_bought": entry["units_bought"],
        "units_purchase_returned": entry["units_purchase_returned"],
        "net_units_bought": net_units_bought,
        # Averages are over gross (pre-return) lines: they describe the
        # prices actually transacted, and stay defined when everything
        # sold in the period also came back.
        "average_selling_price": _ratio(sales_value, entry["units_sold"]),
        "sales_value": sales_value,
        "return_value": return_value,
        "revenue": revenue,
        "purchase_value": purchase_value,
        "purchase_return_value": purchase_return_value,
        "purchase_spend": _money(purchase_value - purchase_return_value),
        "cogs": cogs,
        "gross_profit": gross_profit,
        "margin_pct": margin_pct,
        "profit_per_unit": profit_per_unit,
    }


def build_product_performance_report(
    db: Session,
    *,
    company_id: int,
    from_date: date,
    to_date: date,
    ledger_id: int | None = None,
    product_id: int | None = None,
    sort_by: str = "revenue",
    sort_dir: str = "desc",
    limit: int | None = None,
) -> ProductPerformanceData:
    """Per-product sales, purchases, returns and margin for a period.

    Money is ex-GST throughout. Revenue and purchase spend start from what each
    line billed ex-GST: its ``taxable_amount`` (already net of line discounts)
    after its share of any invoice-level discount and round-off (see
    :func:`_billed_invoices`), less active credit notes: outward notes reduce
    sales, inward (supplier) notes reduce purchases. Every credit note type
    reduces value; only ``return`` notes move units, because a ``discount`` or ``adjustment`` note sends no
    goods back (the credit note service only touches stock for returns).

    Cost: the weighted average ex-GST purchase price, net of in-period inward
    notes against those purchases (``cost_basis="purchases"``), falling back to
    the product's current ``purchase_price`` when it had no purchases in the period
    (``cost_basis="current_price"``). With neither, the cost is unknown and
    every cost-derived field is None rather than a misleading full margin.
    COGS is net units sold x that cost, so returned units take their cost back
    out. The average cost ignores the ledger filter — what a product cost does
    not depend on which customer it was later sold to — while units bought and
    spend shown on the row do honour it.

    Totals cover the returned rows (after ``limit``), like the product sales
    report. Profit totals only cover rows with a known cost, and the margin is
    taken over those rows' revenue so uncosted revenue can't dilute it.
    """
    sales_lines = _discounted_invoice_lines(
        db, company_id=company_id, voucher_type="sales", from_date=from_date,
        to_date=to_date, ledger_id=ledger_id, product_id=product_id,
    )
    purchase_lines = _dated_discounted_invoice_lines(
        db, company_id=company_id, voucher_type="purchase", from_date=from_date,
        to_date=to_date, ledger_id=ledger_id, product_id=product_id,
    )
    cost_lines = purchase_lines
    if ledger_id is not None:
        cost_lines = _dated_discounted_invoice_lines(
            db, company_id=company_id, voucher_type="purchase", from_date=from_date,
            to_date=to_date, ledger_id=None, product_id=product_id,
        )
    note_lines = _credit_note_lines(
        db, company_id=company_id, from_date=from_date, to_date=to_date,
        ledger_id=ledger_id, product_id=product_id,
    )
    cost_notes = note_lines if ledger_id is None else _credit_note_lines(
        db, company_id=company_id, from_date=from_date, to_date=to_date,
        ledger_id=None, product_id=product_id,
    )
    unit_costs = _purchase_unit_costs(_net_purchase_lines(cost_lines, cost_notes))

    acc: dict[int, dict[str, Decimal]] = {}

    def bucket(pid: int) -> dict[str, Decimal]:
        if pid not in acc:
            acc[pid] = _empty_performance_bucket()
        return acc[pid]

    for pid, qty, taxable in sales_lines:
        entry = bucket(pid)
        entry["units_sold"] += qty
        entry["sales_value"] += taxable
    for pid, qty, taxable, _when, _invoice_id in purchase_lines:
        entry = bucket(pid)
        entry["units_bought"] += qty
        entry["purchase_value"] += taxable
    for note in note_lines:
        _add_note_line(
            bucket(note.product_id), note.direction, note.credit_note_type,
            note.quantity, note.taxable_amount,
        )

    if not acc:
        return ProductPerformanceData(rows=[], totals=_performance_totals([]))

    products = {
        product.id: product
        for product in db.query(
            Product.id, Product.name, Product.sku, Product.maintain_inventory, Product.purchase_price,
        ).filter(Product.id.in_(list(acc))).all()
    }
    stock_map = {
        pid: Decimal(str(qty or 0))
        for pid, qty in db.query(Inventory.product_id, Inventory.quantity)
        .filter(Inventory.company_id == company_id, Inventory.product_id.in_(list(acc)))
        .all()
    }

    rows: list[dict] = []
    for pid, entry in acc.items():
        product = products.get(pid)
        if product is None:  # defensive: a line pointing at a deleted product
            continue

        unit_cost, cost_basis = _unit_cost(unit_costs.get(pid), product.purchase_price)
        figures = _performance_figures(entry, unit_cost)
        rows.append({
            "product_id": pid,
            "name": product.name,
            "sku": product.sku,
            **figures,
            "average_buying_price": _money(unit_cost) if unit_cost is not None else None,
            "cost_basis": cost_basis,
            "current_stock": stock_map.get(pid, Decimal("0")) if product.maintain_inventory else None,
        })

    _sort_performance_rows(rows, sort_by=sort_by, sort_dir=sort_dir)
    if limit is not None:
        rows = rows[:limit]

    return ProductPerformanceData(rows=rows, totals=_performance_totals(rows))


def _sort_performance_rows(rows: list[dict], *, sort_by: str, sort_dir: str) -> None:
    """Sort in place; rows whose key is None sort last in both directions."""
    if sort_by not in PRODUCT_PERFORMANCE_SORTS:
        raise ValueError(f"Unsupported sort field: {sort_by}")
    reverse = sort_dir == "desc"

    # Name first, so ties on the real key fall back to a stable, readable order.
    rows.sort(key=lambda row: (row["name"] or "").lower())
    if sort_by == "name":
        if reverse:
            rows.reverse()
        return

    present = [row for row in rows if row[sort_by] is not None]
    missing = [row for row in rows if row[sort_by] is None]
    present.sort(key=lambda row: row[sort_by], reverse=reverse)
    rows[:] = present + missing


def _performance_totals(rows: list[dict]) -> dict:
    def total(field: str, subset: list[dict] | None = None) -> Decimal:
        return sum((row[field] for row in (rows if subset is None else subset)), Decimal("0"))

    costed = [row for row in rows if row["cogs"] is not None]
    costed_revenue = total("revenue", costed)
    gross_profit = total("gross_profit", costed)
    return {
        "product_count": len(rows),
        "units_sold": total("units_sold"),
        "units_returned": total("units_returned"),
        "net_units_sold": total("net_units_sold"),
        "units_bought": total("units_bought"),
        "units_purchase_returned": total("units_purchase_returned"),
        "net_units_bought": total("net_units_bought"),
        "sales_value": total("sales_value"),
        "return_value": total("return_value"),
        "revenue": total("revenue"),
        "purchase_value": total("purchase_value"),
        "purchase_return_value": total("purchase_return_value"),
        "purchase_spend": total("purchase_spend"),
        "costed_revenue": costed_revenue,
        "cogs": total("cogs", costed),
        "gross_profit": gross_profit,
        "margin_pct": _ratio(gross_profit * 100, costed_revenue),
        "uncosted_product_count": len(rows) - len(costed),
        "current_price_product_count": sum(1 for row in rows if row["cost_basis"] == COST_BASIS_CURRENT_PRICE),
    }


@dataclass
class ProductPerformanceDetailData:
    product: dict
    summary: dict | None  # the list row; None when nothing moved in the period
    monthly_rows: list[dict]
    velocity: dict


def build_product_performance_detail(
    db: Session,
    *,
    company_id: int,
    product_id: int,
    from_date: date,
    to_date: date,
    ledger_id: int | None = None,
    today: date | None = None,
) -> ProductPerformanceDetailData | None:
    """One product's performance for a period, with a month-by-month series.

    Returns None when the product does not belong to the company.

    ``summary`` is taken verbatim from :func:`build_product_performance_report`
    under a product filter, so the detail page can never disagree with the row
    it was opened from. That costs the same handful of product-scoped queries
    twice, which is cheap next to the risk of two copies of the rules.

    The months bucket the same lines the period report uses — invoices by
    ``invoice_date``, credit notes by ``credit_note_date`` — through the same
    :func:`_performance_figures`, and every month is costed at the *period's*
    unit cost, so units, revenue, spend, COGS and profit sum exactly to the
    summary. A month's ``average_buying_price`` is different on purpose: it is
    the net cost of purchases made that month (ledger-independent, like the
    period cost), with in-period supplier notes assigned to their purchase's
    month. It is the figure a buyer compares against the selling price.
    """
    product = (
        db.query(
            Product.id, Product.name, Product.sku, Product.unit, Product.maintain_inventory,
            Product.price, Product.purchase_price, Product.reorder_level,
        )
        .filter(Product.id == product_id, Product.company_id == company_id)
        .first()
    )
    if product is None:
        return None

    report = build_product_performance_report(
        db, company_id=company_id, from_date=from_date, to_date=to_date,
        ledger_id=ledger_id, product_id=product_id,
    )
    summary = report.rows[0] if report.rows else None

    def lines(voucher_type: str, ledger: int | None):
        return _dated_discounted_invoice_lines(
            db, company_id=company_id, voucher_type=voucher_type, from_date=from_date,
            to_date=to_date, ledger_id=ledger, product_id=product_id,
        )

    sales_lines = lines("sales", ledger_id)
    purchase_lines = lines("purchase", ledger_id)
    cost_lines = purchase_lines if ledger_id is None else lines("purchase", None)
    note_lines = _credit_note_lines(
        db, company_id=company_id, from_date=from_date, to_date=to_date,
        ledger_id=ledger_id, product_id=product_id,
    )
    cost_notes = note_lines if ledger_id is None else _credit_note_lines(
        db, company_id=company_id, from_date=from_date, to_date=to_date,
        ledger_id=None, product_id=product_id,
    )
    net_cost_lines = _net_purchase_lines(cost_lines, cost_notes)
    period_cost = _purchase_unit_costs(net_cost_lines)
    unit_cost, _ = _unit_cost(period_cost.get(product_id), product.purchase_price)

    months = months_between(from_date, to_date)
    buckets = {key: _empty_performance_bucket() for key in months}
    paid: dict[tuple[int, int], list[Decimal]] = {key: [Decimal("0"), Decimal("0")] for key in months}
    for _, qty, taxable, when, _invoice_id in sales_lines:
        entry = buckets[(when.year, when.month)]
        entry["units_sold"] += qty
        entry["sales_value"] += taxable
    for _, qty, taxable, when, _invoice_id in purchase_lines:
        entry = buckets[(when.year, when.month)]
        entry["units_bought"] += qty
        entry["purchase_value"] += taxable
    for _, qty, taxable, when, _invoice_id in net_cost_lines:
        paid[(when.year, when.month)][0] += taxable
        paid[(when.year, when.month)][1] += qty
    for note in note_lines:
        _add_note_line(
            buckets[(note.credit_note_date.year, note.credit_note_date.month)],
            note.direction, note.credit_note_type, note.quantity, note.taxable_amount,
        )

    # COGS is booked as the change in the rounded running total rather than
    # rounded month by month: per-month rounding of units x an unrounded cost
    # would leave the months a paisa or two off the period's COGS.
    monthly_rows: list[dict] = []
    cumulative_units = booked = Decimal("0")
    for year, month in months:
        entry = buckets[(year, month)]
        month_cogs = None
        if unit_cost is not None:
            cumulative_units += entry["units_sold"] - entry["units_returned"]
            running = _money(cumulative_units * unit_cost)
            month_cogs, booked = running - booked, running
        spend, units = paid[(year, month)]
        monthly_rows.append({
            "month": f"{year:04d}-{month:02d}",
            "label": month_label(year, month),
            **_performance_figures(entry, unit_cost, cogs=month_cogs),
            "average_buying_price": _ratio(spend, units) if units > 0 and spend >= 0 else None,
        })

    current_stock = None
    if product.maintain_inventory:
        stock = (
            db.query(Inventory.quantity)
            .filter(Inventory.company_id == company_id, Inventory.product_id == product_id)
            .scalar()
        )
        current_stock = Decimal(str(stock or 0))

    return ProductPerformanceDetailData(
        product={
            "product_id": product.id,
            "name": product.name,
            "sku": product.sku,
            "unit": product.unit,
            "maintain_inventory": bool(product.maintain_inventory),
            "price": Decimal(str(product.price or 0)),
            "purchase_price": Decimal(str(product.purchase_price or 0)),
            "reorder_level": Decimal(str(product.reorder_level or 0)),
            "current_stock": current_stock,
        },
        summary=summary,
        monthly_rows=monthly_rows,
        velocity=_sales_velocity(
            net_units_sold=summary["net_units_sold"] if summary else Decimal("0"),
            current_stock=current_stock,
            from_date=from_date,
            to_date=to_date,
            today=today or date.today(),
        ),
    )


def _sales_velocity(
    *,
    net_units_sold: Decimal,
    current_stock: Decimal | None,
    from_date: date,
    to_date: date,
    today: date,
) -> dict:
    """Net units sold per day, and how many days today's stock lasts at that rate.

    The rate is over the days of the period that have *happened*: dividing an
    FY's sales so far by all 365 days would understate the pace by however much
    of the year is still to come. Both are None when undefined — nothing sold,
    a period wholly in the future, or a product that isn't stock-tracked —
    because a cover of 0 or infinity would be a claim, not a blank.
    """
    elapsed_days = max((min(to_date, today) - from_date).days + 1, 0)
    daily_rate = None
    if elapsed_days and net_units_sold > 0:
        daily_rate = net_units_sold / elapsed_days
    cover_days = None
    if daily_rate is not None and current_stock is not None:
        cover_days = _money(max(current_stock, Decimal("0")) / daily_rate)
    return {
        "elapsed_days": elapsed_days,
        "daily_sales_rate": daily_rate.quantize(Decimal("0.001")) if daily_rate is not None else None,
        "stock_cover_days": cover_days,
    }


def _distinct_invoice_count(
    db: Session,
    *,
    company_id: int,
    voucher_type: str,
    from_date: date,
    to_date: date,
    ledger_id: int | None,
    product_ids: list[int],
) -> int:
    """Count invoices touching the listed products.

    Summing each row's invoice_count would double-count an invoice that carries
    two different products, so the total needs its own distinct query.
    """
    if not product_ids:
        return 0

    start, end = _date_bounds(from_date, to_date)
    query = (
        db.query(func.count(func.distinct(Invoice.id)))
        .join(InvoiceItem, InvoiceItem.invoice_id == Invoice.id)
        .filter(
            Invoice.company_id == company_id,
            Invoice.status == "active",
            Invoice.voucher_type == voucher_type,
            Invoice.invoice_date >= start,
            Invoice.invoice_date <= end,
            InvoiceItem.product_id.in_(product_ids),
        )
    )
    if ledger_id is not None:
        query = query.filter(Invoice.ledger_id == ledger_id)
    return int(query.scalar() or 0)
