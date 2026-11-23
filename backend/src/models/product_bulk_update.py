from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String, func

from src.db.base import Base


class ProductBulkUpdate(Base):
    __tablename__ = "product_bulk_updates"

    id = Column(String(32), primary_key=True)
    company_id = Column(Integer, ForeignKey("company_profiles.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    changes = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
