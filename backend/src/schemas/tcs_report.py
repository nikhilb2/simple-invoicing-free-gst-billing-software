from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel


class TcsReportRow(BaseModel):
    kind: Literal["invoice", "credit_note"]
    id: int
    document_number: str
    date: date
    invoice_number: str | None = None
    buyer_name: str | None = None
    buyer_pan: str | None = None
    section_ref: str | None = None
    nature: str | None = None
    base_amount: Decimal
    rate: Decimal
    tcs_amount: Decimal
    # Set on a sale that names a section but collected no TCS: "Declaration – not
    # collected" under a s.394(2) declaration (Form 27C), else "Not collected".
    remark: str | None = None


class TcsSectionTotal(BaseModel):
    section_ref: str | None = None
    nature: str | None = None
    count: int
    base_amount: Decimal
    tcs_amount: Decimal
    # Sales under the section on which no TCS was collected. Kept out of base_amount.
    not_collected_base: Decimal = Decimal("0.00")


class TcsReportOut(BaseModel):
    tax_year: int
    quarter: int | None = None
    from_date: date
    to_date: date
    return_form: Literal["Form 27EQ", "Form 143"]
    rows: list[TcsReportRow]
    totals_by_section: list[TcsSectionTotal]
    total_base: Decimal
    total_tcs: Decimal
