"""TDS on receipts (#768) and on payments to suppliers (#770).

A receipt or payment can carry, per invoice, the TDS that was kept back. With
the cash allocated it settles the invoice, but it is never cash: it does not
count towards ``Payment.amount`` and never touches a cash or bank account.

Shared rules (see #766):

* The section table is data with effective dates. The section offered and
  accepted for an invoice is the one in force on the *deduction date*: the
  earlier of the invoice (credit) date and the payment date. For a normal
  receipt or payment that is the invoice date.
* Every allocation stores its own copy of the section reference, the rate and
  the base, so changing the section table never changes a saved voucher.
* The app suggests; the user decides. The amount actually deducted is always
  what the user typed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException
from sqlalchemy.orm import Session

from src.core.validation import pan_from_gstin
from src.models.buyer import Buyer
from src.models.company import CompanyProfile
from src.models.invoice import Invoice
from src.models.tax_withholding_section import TaxWithholdingSection
from src.services.company_access import company_scope, legacy_default_company
from src.services.tax_withholding import suggest_withholding

ZERO = Decimal("0.00")


def money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def as_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    return value


def deduction_date(invoice_date, payment_date=None) -> date:
    """The earlier of credit (invoice date) and payment, which picks the Act (#766)."""
    invoice_day = as_date(invoice_date)
    payment_day = as_date(payment_date)
    if invoice_day is None:
        return payment_day or date.today()
    if payment_day is None:
        return invoice_day
    return min(invoice_day, payment_day)


def tax_year_start(on_date: date) -> date:
    """1 April of the tax year (financial year) that contains ``on_date``."""
    year = on_date.year if on_date.month >= 4 else on_date.year - 1
    return date(year, 4, 1)


def tax_year_label(start_year: int) -> str:
    return f"{start_year}-{str(start_year + 1)[-2:]}"


def quarter_of(on_date: date) -> int:
    """Quarter of the tax year: Q1 Apr-Jun, Q2 Jul-Sep, Q3 Oct-Dec, Q4 Jan-Mar."""
    return ((on_date.month - 4) % 12) // 3 + 1


def quarter_bounds(start_year: int, quarter: int | None) -> tuple[date, date]:
    """Inclusive date bounds of a tax year, or of one of its quarters."""
    if quarter is None:
        return date(start_year, 4, 1), date(start_year + 1, 3, 31)
    starts = {1: (start_year, 4), 2: (start_year, 7), 3: (start_year, 10), 4: (start_year + 1, 1)}
    ends = {1: (start_year, 6, 30), 2: (start_year, 9, 30), 3: (start_year, 12, 31), 4: (start_year + 1, 3, 31)}
    year, month = starts[quarter]
    return date(year, month, 1), date(*ends[quarter])


def section_in_force(section: TaxWithholdingSection, on_date: date) -> bool:
    return section.effective_from <= on_date and (section.effective_to is None or section.effective_to >= on_date)


def section_base(section: TaxWithholdingSection, invoice: Invoice) -> Decimal:
    """The base the section is worked out on: before GST, or the gross bill."""
    if section.base == "gross":
        return money(invoice.total_amount)
    return money(invoice.taxable_amount)


def party_has_pan(ledger: Buyer | None) -> bool:
    if ledger is None:
        return False
    return bool(ledger.pan or pan_from_gstin(ledger.gst))


def holder_type_from_pan(pan: str | None) -> str | None:
    """The PAN holder type, read from the PAN's 4th character."""
    if not pan or len(pan) < 4:
        return None
    return {"P": "individual", "H": "huf", "C": "company", "F": "firm"}.get(pan[3].upper(), "other")


@dataclass
class Deductee:
    """Whose PAN and holder type set the rate: the party the TDS is deducted from."""
    party_type: str | None
    has_pan: bool
    is_self: bool  # True on a receipt: our own business is the deductee


def _company_for(db: Session, company_id: int | None) -> CompanyProfile | None:
    if company_id is not None:
        return db.get(CompanyProfile, company_id)
    return legacy_default_company(db)


def deductee_for(db: Session, invoice: Invoice, ledger: Buyer | None, company_id: int | None) -> Deductee:
    """The deductee of TDS on this invoice.

    On a sales invoice (a receipt, #768) the customer deducts from *us*, so the
    rate follows our company's PAN: 1%/2% by our holder type, and the s.397(2)
    rate when we have no PAN. On a purchase bill (a payment, #770) we deduct
    from the supplier, so it follows the supplier's PAN and party type.
    """
    if invoice.voucher_type == "sales":
        company = _company_for(db, company_id)
        pan = (company.pan or pan_from_gstin(company.gst)) if company is not None else None
        return Deductee(party_type=holder_type_from_pan(pan), has_pan=bool(pan), is_self=True)
    return Deductee(party_type=getattr(ledger, "party_type", None), has_pan=party_has_pan(ledger), is_self=False)


def deductee_rate(section: TaxWithholdingSection, deductee: Deductee) -> Decimal:
    suggestion = suggest_withholding(section, 0, deductee.party_type, deductee.has_pan)
    return Decimal(str(suggestion["rate"]))


def section_label(section_ref: str | None) -> str:
    """'s.393(1) Sl. No. 6(iii)' for the 2025 Act, 's.194J' for the 1961 Act."""
    if not section_ref:
        return ""
    return f"s.{section_ref}"


@dataclass
class NormalizedAllocation:
    invoice: Invoice
    allocated_amount: Decimal
    tds_amount: Decimal = ZERO
    section: TaxWithholdingSection | None = None
    rate: Decimal | None = None
    base_amount: Decimal | None = None


class TdsContext:
    """Validates the TDS part of each allocation on one receipt or payment."""

    def __init__(
        self,
        db: Session,
        *,
        voucher_type: str,
        ledger_id: int | None,
        company_id: int | None,
        previous_allocations: dict | None = None,
    ):
        self.db = db
        self.voucher_type = voucher_type
        self.ledger_id = ledger_id
        self.company_id = company_id
        # invoice_id -> the allocation an edit replaces (empty on a new voucher).
        self.previous_allocations = previous_allocations or {}
        self._ledger: Buyer | None = None
        self._ledger_loaded = False

    @property
    def ledger(self) -> Buyer | None:
        if not self._ledger_loaded:
            self._ledger = self.db.get(Buyer, self.ledger_id) if self.ledger_id is not None else None
            self._ledger_loaded = True
        return self._ledger

    def _unchanged_from_previous(self, invoice: Invoice, tds_amount: Decimal, section_id: int | None) -> bool:
        previous = self.previous_allocations.get(invoice.id)
        return (
            previous is not None
            and money(previous.tds_amount) == tds_amount
            and previous.tds_section_id == section_id
        )

    def _require_purchase_tds_enabled(self) -> None:
        company = _company_for(self.db, self.company_id)
        if company is None or not company.enable_purchase_tds:
            raise HTTPException(
                status_code=400,
                detail="TDS on payments to suppliers is turned off. Turn it on in Company settings first.",
            )

    def normalize(
        self,
        invoice: Invoice,
        allocated_amount: Decimal,
        tds_amount: Decimal,
        section_id: int | None,
        *,
        payment_date: date | None = None,
    ) -> NormalizedAllocation:
        if tds_amount <= 0:
            return NormalizedAllocation(invoice=invoice, allocated_amount=allocated_amount)

        # With the setting turned off, a payment entered while it was on can
        # still be edited as long as its TDS stays exactly as it was.
        if self.voucher_type == "payment" and not self._unchanged_from_previous(invoice, tds_amount, section_id):
            self._require_purchase_tds_enabled()

        label = invoice.invoice_number or invoice.id
        if section_id is None:
            raise HTTPException(status_code=400, detail=f"Choose the TDS section for invoice {label}")
        section = self.db.get(TaxWithholdingSection, section_id)
        if section is None or section.kind != "tds":
            raise HTTPException(status_code=400, detail=f"TDS section {section_id} not found")

        on_date = deduction_date(invoice.invoice_date, payment_date)
        if not section_in_force(section, on_date):
            act = "Income-tax Act 1961" if on_date < date(2026, 4, 1) else "Income-tax Act 2025"
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Section {section.section_ref} is not in force on {on_date.isoformat()}, "
                    f"the date of invoice {label}. Choose a section of the {act}."
                ),
            )

        return NormalizedAllocation(
            invoice=invoice,
            allocated_amount=allocated_amount,
            tds_amount=tds_amount,
            section=section,
            rate=deductee_rate(section, deductee_for(self.db, invoice, self.ledger, self.company_id)),
            base_amount=taxed_base(self.db, invoice, section, on_date, self.company_id),
        )


def allocation_tds_columns(row: NormalizedAllocation, previous=None) -> dict:
    """Column values for a new PaymentInvoiceAllocation row.

    ``previous`` is the row this one replaces on an edit. When the section did
    not change, its stored copies are kept, so an edit never re-reads a newer
    section row or a changed party PAN, and a ticked certificate stays ticked.
    """
    if row.tds_amount <= 0 or row.section is None:
        return {"tds_amount": 0}

    columns = {
        "tds_amount": float(row.tds_amount),
        "tds_section_id": row.section.id,
        "tds_section_ref": row.section.section_ref,
        "tds_rate": float(row.rate) if row.rate is not None else None,
        "tds_base_amount": float(row.base_amount) if row.base_amount is not None else None,
        "tds_certificate_received": False,
    }
    if previous is not None and previous.tds_section_id == row.section.id and Decimal(str(previous.tds_amount or 0)) > 0:
        columns["tds_section_ref"] = previous.tds_section_ref or columns["tds_section_ref"]
        if previous.tds_rate is not None:
            columns["tds_rate"] = float(previous.tds_rate)
        if previous.tds_base_amount is not None:
            columns["tds_base_amount"] = float(previous.tds_base_amount)
        columns["tds_certificate_received"] = bool(previous.tds_certificate_received)
    return columns


# ---------------------------------------------------------------------------
# Suggestion
# ---------------------------------------------------------------------------

def _money_text(value: Decimal) -> str:
    """₹ with Indian digit grouping: ₹1,00,000.00."""
    whole, _, paise = f"{money(value):.2f}".partition(".")
    sign = "-" if whole.startswith("-") else ""
    whole = whole.lstrip("-")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return f"{sign}₹{whole}.{paise}"


def _supplier_year_bases(
    db: Session,
    invoice: Invoice,
    section: TaxWithholdingSection,
    on_date: date,
    company_id: int | None,
) -> Decimal:
    """Sum of the section base of this party's invoices of the same type (bills
    from a supplier, or sales to a customer) in the tax year, up to and
    including this one."""
    year_start = datetime.combine(tax_year_start(on_date), datetime.min.time())
    query = db.query(Invoice).filter(
        Invoice.ledger_id == invoice.ledger_id,
        Invoice.voucher_type == invoice.voucher_type,
        Invoice.status == "active",
        Invoice.invoice_date >= year_start,
        Invoice.invoice_date <= invoice.invoice_date,
    )
    if company_id is not None:
        query = query.filter(company_scope(Invoice.company_id, company_id))
    total = ZERO
    seen_self = False
    for other in query.all():
        if other.id == invoice.id:
            seen_self = True
        elif as_date(other.invoice_date) == as_date(invoice.invoice_date) and other.id > invoice.id:
            # Same day, entered later: comes after this bill.
            continue
        total += section_base(section, other)
    if not seen_self:
        total += section_base(section, invoice)
    return money(total)


def _excess_over_threshold(
    db: Session,
    invoice: Invoice,
    section: TaxWithholdingSection,
    on_date: date,
    company_id: int | None,
) -> tuple[Decimal, Decimal, Decimal] | None:
    """For an "excess over threshold" section (s.393(1) Sl. No. 8(ii), 194Q):
    (the part of this invoice above the tax-year threshold, the year's total, the threshold).
    None for any other section."""
    if section.threshold_note != "excess over threshold" or section.threshold_aggregate is None:
        return None
    aggregate = Decimal(str(section.threshold_aggregate))
    bill_base = section_base(section, invoice)
    year_total = _supplier_year_bases(db, invoice, section, on_date, company_id)
    before = year_total - bill_base
    above = max(ZERO, year_total - aggregate) - max(ZERO, before - aggregate)
    return money(above), year_total, aggregate


def taxed_base(
    db: Session,
    invoice: Invoice,
    section: TaxWithholdingSection,
    on_date: date,
    company_id: int | None,
) -> Decimal:
    """The base the TDS is worked out on: the invoice's section base, or only the
    part above the threshold for an "excess over threshold" section."""
    excess = _excess_over_threshold(db, invoice, section, on_date, company_id)
    if excess is not None:
        return excess[0]
    return section_base(section, invoice)


def suggest_tds_for_invoice(
    db: Session,
    invoice: Invoice,
    section: TaxWithholdingSection,
    *,
    ledger: Buyer | None,
    payment_date: date | None = None,
    company_id: int | None = None,
) -> dict:
    """Suggested TDS for one invoice and section. Never binding.

    Receipts (sales invoices): the customer decides whether to deduct, so the
    suggestion is just rate x base, with no threshold check.

    Payments (purchase bills): we decide, so the per-bill and tax-year
    thresholds of the section are checked against this supplier's bills, and
    for purchase of goods only the part above the threshold is suggested.
    """
    on_date = deduction_date(invoice.invoice_date, payment_date)
    bill_base = section_base(section, invoice)
    deductee = deductee_for(db, invoice, ledger, company_id)
    has_pan = deductee.has_pan
    party_type = deductee.party_type
    result = {
        "invoice_id": invoice.id,
        "section_id": section.id,
        "section_ref": section.section_ref,
        "act": section.act,
        "nature": section.nature,
        "deduction_date": on_date,
        "in_force": section_in_force(section, on_date),
        "has_pan": has_pan,
        "base_amount": float(bill_base),
        "rate": 0.0,
        "amount": 0.0,
        "applies": True,
        "reason": None,
    }
    if not result["in_force"]:
        result["applies"] = False
        result["reason"] = f"Section {section.section_ref} is not in force on {on_date.isoformat()}."
        return result

    base = bill_base
    reasons: list[str] = []
    excess = _excess_over_threshold(db, invoice, section, on_date, company_id)
    if excess is not None:
        # Purchase of goods: TDS only on the part above the threshold, on either side.
        above, year_total, aggregate = excess
        result["tax_year_total"] = float(year_total)
        if above <= 0:
            whose = "Bills from this supplier" if invoice.voucher_type == "purchase" else "Sales to this customer"
            result["applies"] = False
            result["reason"] = (
                f"{whose} this tax year come to {_money_text(year_total)}, "
                f"not above {_money_text(aggregate)}. No TDS is due yet."
            )
            return result
        base = above
        if base < bill_base:
            reasons.append(f"TDS is only on the {_money_text(base)} above {_money_text(aggregate)} for the tax year.")
    elif invoice.voucher_type == "purchase":
        single = Decimal(str(section.threshold_single)) if section.threshold_single is not None else None
        aggregate = Decimal(str(section.threshold_aggregate)) if section.threshold_aggregate is not None else None
        year_total = _supplier_year_bases(db, invoice, section, on_date, company_id)
        result["tax_year_total"] = float(year_total)
        over_single = single is not None and bill_base > single
        over_aggregate = aggregate is not None and year_total > aggregate
        if single is None and aggregate is None:
            pass
        elif not over_single and not over_aggregate:
            parts = []
            if single is not None:
                per = "a month" if section.threshold_note == "per month" else "per bill"
                parts.append(f"this bill ({_money_text(bill_base)}) is not above {_money_text(single)} {per}")
            if aggregate is not None:
                parts.append(
                    f"bills from this supplier this tax year ({_money_text(year_total)}) "
                    f"are not above {_money_text(aggregate)}"
                )
            result["applies"] = False
            result["reason"] = ("No TDS suggested: " + " and ".join(parts) + ".")
            return result
        elif over_aggregate and not over_single:
            reasons.append(
                f"This bill takes the tax year's total to {_money_text(year_total)}, above {_money_text(aggregate)}. "
                "Earlier bills this year may also need TDS."
            )

    suggestion = suggest_withholding(section, base, party_type, has_pan)
    result["base_amount"] = float(base)
    result["rate"] = suggestion["rate"]
    result["amount"] = suggestion["amount"]
    higher_rate_section = "s.206AA" if section.act == 1961 else "s.397(2)"
    if deductee.is_self:
        # On a receipt our business is the deductee: the customer's PAN plays no part.
        if not has_pan:
            reasons.append(
                f"Your business has no PAN on file, so the customer must deduct at the higher rate of "
                f"{higher_rate_section}. Add your PAN in Company settings."
            )
        elif Decimal(str(section.rate_individual_huf)) != Decimal(str(section.rate_other)):
            holder = "an individual or HUF" if party_type in {"individual", "huf"} else "not an individual or HUF"
            reasons.append(f"The rate follows your business's PAN: {suggestion['rate']:g}% because it is {holder}.")
    elif not has_pan:
        reasons.append(f"The supplier has no PAN, so the higher rate of {higher_rate_section} applies.")
    result["reason"] = " ".join(reasons) or None
    return result
