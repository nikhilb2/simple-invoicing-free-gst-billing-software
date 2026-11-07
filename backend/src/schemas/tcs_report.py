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


class TcsSectionTotal(BaseModel):
    section_ref: str | None = None
    nature: str | None = None
    count: int
    base_amount: Decimal
    tcs_amount: Decimal


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
