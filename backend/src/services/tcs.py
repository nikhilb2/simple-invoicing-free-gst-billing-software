"""TCS (tax collected at source) on sales documents, s.394(1) of the Income-tax Act 2025.

Under the 1961 Act this was s.206C. A seller of scrap, liquor, coal, forest produce,
motor vehicles and a few other goods adds TCS to the bill and collects it from the
buyer. See issue #766 for the legal background and #769 for this feature.

The rules this module keeps:

* Rates are data. The section comes from ``tax_withholding_sections`` and must be in
  force on the document's date, so a sale dated 25 March 2026 uses a 1961 section and
  one dated 15 April 2026 a 2025 one.
* Suggest, don't decide. A rate left out is suggested from the section and the buyer
  (no PAN: the section's ``rate_no_pan``; a s.394(2) declaration on Sl. No. 1 to 5
  goods: nothing). A rate or amount the user sends always wins.
* TCS never touches the GST figures. :func:`src.services.document_totals.
  apply_discount_and_round_off` adds it after the invoice discount and before the
  round-off, so ``total_amount = taxable + tax - discount + tcs + round-off``.
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException
from sqlalchemy.orm import Session

from src.core.validation import pan_from_gstin
from src.models.tax_withholding_section import TaxWithholdingSection
from src.services.gst_tax_service import money as _money
from src.services.tax_withholding import suggest_withholding

# The goods a s.394(2) declaration covers: Sl. No. 1 to 5 of the s.394(1) table, which
# were all s.206C(1) under the 1961 Act. Read off the data, so a new row for the same
# goods is covered without a code change.
DECLARATION_LEGACY_CODES = frozenset({"206C(1)"})


@dataclass(frozen=True)
class TcsCharge:
    """The TCS a document should carry, before its amount is worked out."""

    section_id: int
    section_ref: str
    # 'gross' (taxable + GST - invoice discount) or 'taxable' (the pre-GST part of it).
    base_kind: str
    rate: Decimal
    # What the user typed as actually collected. None works it out as base x rate.
    amount: Decimal | None = None


def in_force_on(on_date: date):
    """The filter for sections in force on ``on_date``."""
    return (
        (TaxWithholdingSection.effective_from <= on_date)
        & (TaxWithholdingSection.effective_to.is_(None) | (TaxWithholdingSection.effective_to >= on_date))
    )


def tcs_section_in_force(db: Session, section_id: int, on_date: date) -> TaxWithholdingSection | None:
    return (
        db.query(TaxWithholdingSection)
        .filter(
            TaxWithholdingSection.id == section_id,
            TaxWithholdingSection.kind == "tcs",
            in_force_on(on_date),
        )
        .first()
    )


def successor_section(db: Session, section_id: int | None, on_date: date) -> TaxWithholdingSection | None:
    """The section to use on ``on_date`` for goods first billed under ``section_id``.

    The section itself while it is in force. Otherwise the row for the same goods in
    force on the new date: same ``legacy_code`` and ``nature``, or failing that the one
    row with the same ``legacy_code``. Used when a document is copied to a new date,
    such as a March 2026 invoice duplicated in April 2026. None when nothing matches,
    and the copy then carries no TCS for the user to pick again.
    """
    if section_id is None:
        return None
    original = db.query(TaxWithholdingSection).filter(TaxWithholdingSection.id == section_id).first()
    if original is None:
        return None
    if tcs_section_in_force(db, section_id, on_date) is not None:
        return original
    candidates = (
        db.query(TaxWithholdingSection)
        .filter(
            TaxWithholdingSection.kind == original.kind,
            TaxWithholdingSection.legacy_code == original.legacy_code,
            in_force_on(on_date),
        )
        .all()
    )
    same_nature = [row for row in candidates if row.nature == original.nature]
    if len(same_nature) == 1:
        return same_nature[0]
    return candidates[0] if len(candidates) == 1 else None


def buyer_has_pan(ledger) -> bool:
    return bool((getattr(ledger, "pan", None) or "").strip() or pan_from_gstin(getattr(ledger, "gst", None)))


def declaration_covers(section: TaxWithholdingSection, ledger) -> bool:
    """Whether the buyer's s.394(2) declaration takes this sale out of TCS."""
    return bool(getattr(ledger, "tcs_declaration_received", False)) and section.legacy_code in DECLARATION_LEGACY_CODES


def suggest_tcs_rate(section: TaxWithholdingSection, ledger) -> Decimal:
    """The rate to offer for this buyer. The user can always change it."""
    if declaration_covers(section, ledger):
        return Decimal("0")
    suggestion = suggest_withholding(section, 0, getattr(ledger, "party_type", None), buyer_has_pan(ledger))
    return Decimal(str(suggestion["rate"]))


def tcs_base(net_total: Decimal, gross_total: Decimal, taxable_total: Decimal, base_kind: str) -> Decimal:
    """The amount TCS is worked out on.

    ``net_total`` is what the buyer pays before TCS (taxable + GST - invoice discount),
    ``gross_total`` the same before the invoice discount. A 'taxable' section takes the
    pre-GST share of ``net_total``, in the proportion taxable : taxable + GST.
    ``frontend/src/utils/invoiceTotals.ts`` mirrors this.
    """
    if base_kind != "taxable":
        return _money(net_total)
    if gross_total <= 0:
        return Decimal("0.00")
    return _money(net_total * taxable_total / gross_total)


def tcs_amount_for(base: Decimal, rate: Decimal) -> Decimal:
    return _money(base * rate / Decimal("100"))


def resolve_tcs(
    db: Session,
    *,
    tcs_section_id: int | None,
    tcs_rate: float | None,
    tcs_amount: float | None,
    company,
    ledger,
    document_date: date,
    voucher_type: str = "sales",
    already_has_tcs: bool = False,
) -> TcsCharge | None:
    """Check the TCS a payload asks for and return what to charge, or None for no TCS.

    A company with TCS turned off can still save a document that already carries TCS,
    so turning the setting off never strands an old invoice; it cannot add TCS to a
    new one.
    """
    if tcs_section_id is None:
        if tcs_amount:
            raise HTTPException(status_code=400, detail="Choose the TCS section for the TCS amount.")
        return None
    if voucher_type != "sales":
        raise HTTPException(status_code=400, detail="TCS can only be added to a sales invoice.")
    if not (company is not None and getattr(company, "enable_tcs", False)) and not already_has_tcs:
        raise HTTPException(
            status_code=400,
            detail="TCS is turned off for this company. Turn it on in Company settings first.",
        )
    section = tcs_section_in_force(db, tcs_section_id, document_date)
    if section is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"TCS section {tcs_section_id} is not in force on {document_date.isoformat()}. "
                "Choose a section for this date."
            ),
        )
    # The column holds three places, so the amount is worked out from the rate as stored.
    rate = Decimal(str(tcs_rate)) if tcs_rate is not None else suggest_tcs_rate(section, ledger)
    rate = rate.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    amount = _money(Decimal(str(tcs_amount))) if tcs_amount is not None else None
    return TcsCharge(
        section_id=section.id,
        section_ref=section.section_ref,
        base_kind=section.base,
        rate=rate,
        amount=amount,
    )


def copied_tcs_fields(db: Session, document, on_date: date, company) -> dict:
    """The TCS payload fields that copy ``document`` (invoice or quotation) to ``on_date``.

    Nothing when the company has since turned TCS off: the copy is a new document. Keeps the section while it is in force, or moves to its successor (see
    :func:`successor_section`). The rate is kept only when the section is unchanged;
    otherwise it is left out so the new section suggests one. An amount the user typed
    over the worked-out one is kept too, on the same section and rate.
    """
    if not getattr(company, "enable_tcs", False):
        return {}
    section = successor_section(db, getattr(document, "tcs_section_id", None), on_date)
    if section is None:
        return {}
    if section.id != document.tcs_section_id or document.tcs_rate is None:
        return {"tcs_section_id": section.id}
    rate = Decimal(str(document.tcs_rate))
    fields = {"tcs_section_id": section.id, "tcs_rate": float(rate)}
    stored = _money(Decimal(str(document.tcs_amount or 0)))
    if stored != tcs_amount_for(Decimal(str(document.tcs_base_amount or 0)), rate):
        fields["tcs_amount"] = float(stored)
    return fields
