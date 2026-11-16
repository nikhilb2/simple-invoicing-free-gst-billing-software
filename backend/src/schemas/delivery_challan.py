"""Delivery challans (#840). A priced list of goods, with no discounts, round-off,
TDS/TCS, payments or due date: a challan is not a bill."""

from datetime import date, datetime
from typing import List, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.core.document_limits import MONEY_LIMIT, QUANTITY_LIMIT
from src.core.validation import normalize_place_of_supply
from src.schemas.invoice import InvoiceCreate
from src.schemas.ledger_address import ShippingAddressInline
from src.schemas.quotation import (
    EARLIEST_DOCUMENT_DATE,
    LATEST_DOCUMENT_DATE,
    ConversionWarning,
    LinkedInvoiceOut,
    _check_places,
)

ChallanStatus = Literal["open", "invoiced", "cancelled"]
ChallanPurpose = Literal[
    "supply_on_approval", "job_work", "liquid_gas", "skd_ckd_lots", "exhibition", "own_use", "other"
]

__all__ = [
    "ChallanStatus",
    "ChallanPurpose",
    "ConversionWarning",
    "LinkedInvoiceOut",
    "DeliveryChallanItemCreate",
    "DeliveryChallanFields",
    "DeliveryChallanCreate",
    "DeliveryChallanUpdate",
    "DeliveryChallanItemOut",
    "DeliveryChallanOut",
    "PaginatedDeliveryChallanOut",
    "DeliveryChallanConvert",
    "ChallanConversionLine",
    "DeliveryChallanConversionDraft",
]


class DeliveryChallanItemCreate(BaseModel):
    """One line. A price or GST rate left out comes from the product."""

    product_id: int
    quantity: float = Field(lt=QUANTITY_LIMIT, allow_inf_nan=False)
    unit_price: float | None = Field(default=None, ge=0, lt=MONEY_LIMIT, allow_inf_nan=False)
    # Captured per line for the invoice later and for the e-way bill.
    gst_rate: float | None = Field(default=None, ge=0, le=100)
    description: str | None = None

    @field_validator("product_id")
    @classmethod
    def _check_product_id(cls, value: int) -> int:
        # A line whose product was typed but never picked arrives as 0.
        if value <= 0:
            raise ValueError("Choose a product from the list for every line.")
        return value

    @field_validator("unit_price", mode="after")
    @classmethod
    def _check_unit_price(cls, value: float | None) -> float | None:
        return _check_places(value, 2)

    @field_validator("quantity", mode="after")
    @classmethod
    def _check_quantity(cls, value: float) -> float:
        return _check_places(value, 3)


class DeliveryChallanFields(BaseModel):
    ledger_id: int
    # Stripped, and blank counts as left out. Left out on create: the next number in
    # the delivery challan series. Left out on update: kept.
    challan_number: str | None = None
    # Left out: today on create, kept on update.
    challan_date: date | None = Field(default=None, ge=EARLIEST_DOCUMENT_DATE, le=LATEST_DOCUMENT_DATE)
    purpose: ChallanPurpose = "supply_on_approval"
    place_of_supply: str | None = None
    shipping_address_same_as_billing: bool = True
    shipping_address_id: int | None = None
    new_shipping_address: ShippingAddressInline | None = None
    reference_notes: str | None = None
    # Left out on create: the company's terms. Left out on update: kept. Blank: none.
    terms_text: str | None = None
    items: List[DeliveryChallanItemCreate]

    @field_validator("challan_number", mode="before")
    @classmethod
    def _strip_number(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("place_of_supply")
    @classmethod
    def _check_place_of_supply(cls, value: str | None) -> str | None:
        return normalize_place_of_supply(value)


class DeliveryChallanCreate(DeliveryChallanFields):
    pass


class DeliveryChallanUpdate(DeliveryChallanFields):
    model_config = ConfigDict(extra="forbid")


class DeliveryChallanItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    product_name: str | None = None
    unit: str | None = None
    hsn_sac: str | None = None
    quantity: float
    unit_price: float
    gst_rate: float
    taxable_amount: float
    tax_amount: float
    cgst_amount: float
    sgst_amount: float
    igst_amount: float
    line_total: float
    description: str | None = None


class DeliveryChallanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    challan_number: str
    status: str
    purpose: str
    purpose_label: str
    challan_date: date
    financial_year_id: int | None = None
    ledger_id: int
    ledger_name: str | None = None
    ledger_address: str | None = None
    ledger_gst: str | None = None
    ledger_phone: str | None = None
    company_name: str | None = None
    company_address: str | None = None
    company_gst: str | None = None
    company_currency_code: str | None = None
    place_of_supply: str | None = None
    shipping_address: str | None = None
    shipping_address_label: str | None = None
    shipping_address_id: int | None = None
    reference_notes: str | None = None
    terms_text: str | None = None
    taxable_amount: float
    total_tax_amount: float
    cgst_amount: float
    sgst_amount: float
    igst_amount: float
    total_amount: float
    # Days since the challan date while open; None once invoiced or cancelled.
    age_days: int | None = None
    invoiced_at: datetime | None = None
    cancelled_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    items: list[DeliveryChallanItemOut] = Field(default_factory=list)
    # The one live invoice, if any, then every invoice ever made from this challan.
    invoice_id: int | None = None
    invoice_number: str | None = None
    invoices: list[LinkedInvoiceOut] = Field(default_factory=list)


class PaginatedDeliveryChallanOut(BaseModel):
    items: list[DeliveryChallanOut]
    total: int
    page: int
    page_size: int
    total_pages: int
    # Per status, across the filters other than status itself.
    status_counts: dict[str, int] = Field(default_factory=dict)


class DeliveryChallanConvert(InvoiceCreate):
    """What /convert takes: the invoice, and which version of the challan it came from.

    The draft fills in the version, so posting a draft back is checked for staleness.
    Left out, nothing is checked.
    """

    challan_updated_at: datetime | None = None


class ChallanConversionLine(BaseModel):
    product_id: int
    product_name: str | None = None
    quantity: float


class DeliveryChallanConversionDraft(BaseModel):
    challan_id: int
    challan_number: str
    challan_date: date
    # Ready to review in the composer, then post back to /convert. Leaves gst_rate and
    # hsn_sac unset, so both come from the product as it stands today.
    invoice: DeliveryChallanConvert
    # One per challan line, in line order: what the composer compares quantities with.
    challan_items: list[ChallanConversionLine]
    warnings: list[ConversionWarning] = Field(default_factory=list)
