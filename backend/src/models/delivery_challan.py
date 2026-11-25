"""Delivery challans (#840): goods sent to a buyer, under GST Rule 55.

A challan lists goods that leave the premises before (or without) a bill: supply on
approval, job work, exhibitions, branch transfers and the like. It is not a bill. It
moves stock, and nothing else: no ledger entry, no payment, no GST liability, no GST
report. Like quotations it lives in its own tables, so every query that has never
heard of challans (sales registers, GSTR-1, ledgers) is already correct.

Stock: a challan holds its goods out of stock only while it is ``open``. Converting
it releases that hold and the invoice's own sale takes over; cancelling it puts the
goods back. See :mod:`src.services.delivery_challan` for the movements.

``invoices.source_challan_id`` links the invoice made from a challan. It sits on the
invoice side, so the history survives the invoice being cancelled.

Columns carry the same names as their ``invoices`` counterparts, and the money columns
the same precision, so the shared totals, PDF and e-way bill helpers work on either.
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import deferred, relationship

from src.db.base import Base

STATUS_OPEN = "open"
STATUS_INVOICED = "invoiced"
STATUS_CANCELLED = "cancelled"
STATUSES = (STATUS_OPEN, STATUS_INVOICED, STATUS_CANCELLED)

PURPOSE_SUPPLY_ON_APPROVAL = "supply_on_approval"
PURPOSE_JOB_WORK = "job_work"
PURPOSE_LIQUID_GAS = "liquid_gas"
PURPOSE_SKD_CKD_LOTS = "skd_ckd_lots"
PURPOSE_EXHIBITION = "exhibition"
PURPOSE_OWN_USE = "own_use"
PURPOSE_OTHER = "other"
PURPOSE_LABELS: dict[str, str] = {  # insertion order = dropdown order
    "supply_on_approval": "Supply on approval",
    "job_work": "Job work",
    "liquid_gas": "Supply of liquid gas (quantity not known)",
    "skd_ckd_lots": "SKD/CKD or in lots",
    "exhibition": "Exhibition or fair",
    "own_use": "For own use / branch transfer",
    "other": "Other",
}
PURPOSES = tuple(PURPOSE_LABELS)
DEFAULT_PURPOSE = PURPOSE_SUPPLY_ON_APPROVAL


class DeliveryChallan(Base):
    __tablename__ = "delivery_challans"
    __table_args__ = (
        UniqueConstraint("company_id", "challan_number", name="uq_delivery_challans_company_number"),
        Index("ix_delivery_challans_company_status", "company_id", "status"),
        Index("ix_delivery_challans_company_date", "company_id", "challan_date"),
    )

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("company_profiles.id"), nullable=False)
    # Rule 55: at most 16 characters, unique per company.
    challan_number = Column(String(16), nullable=False)
    status = Column(String(16), nullable=False, default=STATUS_OPEN)
    purpose = Column(String(32), nullable=False, default=DEFAULT_PURPOSE)
    challan_date = Column(Date, nullable=False)
    financial_year_id = Column(Integer, ForeignKey("financial_years.id"), nullable=True)

    # The consignee.
    ledger_id = Column(Integer, ForeignKey("buyers.id"), nullable=False, index=True)
    ledger_name = Column(String, nullable=True)
    ledger_address = Column(String, nullable=True)
    ledger_gst = Column(String, nullable=True)
    ledger_phone = Column(String, nullable=True)

    company_name = Column(String, nullable=True)
    company_address = Column(String, nullable=True)
    company_gst = Column(String, nullable=True)
    company_phone = Column(String, nullable=True)
    company_email = Column(String, nullable=True)
    company_website = Column(String, nullable=True)
    company_currency_code = Column(String, nullable=True)
    company_bank_name = Column(String, nullable=True)
    company_branch_name = Column(String, nullable=True)
    company_account_name = Column(String, nullable=True)
    company_account_number = Column(String, nullable=True)
    company_ifsc_code = Column(String, nullable=True)
    # Base64, and only the PDF wants it: not worth carrying on every list row.
    company_logo_data = deferred(Column(Text, nullable=True))
    company_logo_mime_type = Column(String(50), nullable=True)
    company_additional_info = Column(Text, nullable=True)
    company_terms_text = Column(Text, nullable=True)

    # GST state code the goods go to.
    place_of_supply = Column(String(2), nullable=True)
    shipping_address = Column(Text, nullable=True)
    shipping_address_label = Column(String(255), nullable=True)
    # Kept alongside the snapshot so conversion can hand the invoice the saved address
    # by id rather than adding a duplicate ledger_addresses row.
    shipping_address_id = Column(
        Integer, ForeignKey("ledger_addresses.id", ondelete="SET NULL"), nullable=True
    )

    # "Notes" on the form and the PDF.
    reference_notes = Column(String, nullable=True)
    # "Terms & conditions" on the form and the PDF.
    terms_text = Column(Text, nullable=True)

    # The value of the goods, and the tax an invoice for them would carry. Stored for
    # the e-way bill and as an estimate; never printed on the challan.
    taxable_amount = Column(Numeric(10, 2), nullable=False, default=0)
    total_tax_amount = Column(Numeric(10, 2), nullable=False, default=0)
    cgst_amount = Column(Numeric(10, 2), nullable=False, default=0)
    sgst_amount = Column(Numeric(10, 2), nullable=False, default=0)
    igst_amount = Column(Numeric(10, 2), nullable=False, default=0)
    total_amount = Column(Numeric(10, 2), nullable=False, default=0)

    invoiced_at = Column(DateTime, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)

    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    ledger = relationship("Buyer")
    items = relationship(
        "DeliveryChallanItem",
        back_populates="challan",
        cascade="all, delete-orphan",
        order_by="DeliveryChallanItem.id",
    )

    @property
    def purpose_label(self) -> str:
        return PURPOSE_LABELS.get(self.purpose, self.purpose)


class DeliveryChallanItem(Base):
    """One line. No serial column: serial-numbered products are refused on a challan."""

    __tablename__ = "delivery_challan_items"

    id = Column(Integer, primary_key=True, index=True)
    challan_id = Column(
        Integer, ForeignKey("delivery_challans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    hsn_sac = Column(String, nullable=True)
    quantity = Column(Numeric(12, 3), nullable=False)
    unit_price = Column(Numeric(10, 2), nullable=False)
    gst_rate = Column(Numeric(5, 2), nullable=False, default=0)
    taxable_amount = Column(Numeric(10, 2), nullable=False, default=0)
    tax_amount = Column(Numeric(10, 2), nullable=False, default=0)
    cgst_amount = Column(Numeric(10, 2), nullable=False, default=0)
    sgst_amount = Column(Numeric(10, 2), nullable=False, default=0)
    igst_amount = Column(Numeric(10, 2), nullable=False, default=0)
    line_total = Column(Numeric(10, 2), nullable=False)
    description = Column(Text, nullable=True)
    # Whether this line holds its goods out of stock, fixed when the challan takes
    # them out. Releasing it (cancel, edit, invoicing) puts back only what it took,
    # even if "Maintain inventory" was switched since (#1067). NULL means unknown
    # and falls back to the product's current setting.
    stock_applied = Column(Boolean, nullable=True)

    challan = relationship("DeliveryChallan", back_populates="items")
