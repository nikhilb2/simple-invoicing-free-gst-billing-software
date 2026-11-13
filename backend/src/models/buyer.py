from sqlalchemy import Boolean, Column, Integer, String, DateTime, ForeignKey, text
from sqlalchemy.orm import relationship
from datetime import datetime
from src.db.base import Base



class Buyer(Base):
    __tablename__ = "buyers"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("company_profiles.id"), nullable=True, index=True)
    name = Column(String, nullable=False, index=True)
    address = Column(String, nullable=False)
    gst = Column(String, nullable=True, index=True)
    pan = Column(String(10), nullable=True, index=True)
    party_type = Column(String(20), nullable=True)
    # The buyer gave a s.394(2) declaration (Sl. No. 1 to 5 goods bought for
    # manufacturing), so no TCS is suggested on sales to them.
    tcs_declaration_received = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    phone_number = Column(String, nullable=False)
    email = Column(String, nullable=True)
    website = Column(String, nullable=True)
    bank_name = Column(String, nullable=True)
    branch_name = Column(String, nullable=True)
    account_name = Column(String, nullable=True)
    account_number = Column(String, nullable=True)
    ifsc_code = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    invoices = relationship("Invoice", back_populates="ledger")
    addresses = relationship("LedgerAddress", back_populates="ledger", cascade="all, delete-orphan")
