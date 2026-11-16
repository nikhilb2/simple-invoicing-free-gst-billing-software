"""Builds and renders the delivery challan PDF."""

from io import BytesIO

import weasyprint
from fastapi import HTTPException
from sqlalchemy.orm import Session, selectinload

from src.models.company import CompanyProfile
from src.models.delivery_challan import DeliveryChallan
from src.models.product import Product
from src.services.pdf_render import safe_url_fetcher
from src.services.pdf_templates.delivery_challan_template import _build_multi_copy_delivery_challan_html


def build_delivery_challan_html(db: Session, company_id: int, challan_id: int, *, copies: int = 1) -> str:
    challan = (
        db.query(DeliveryChallan)
        .options(selectinload(DeliveryChallan.items))
        .filter(DeliveryChallan.id == challan_id, DeliveryChallan.company_id == company_id)
        .first()
    )
    if challan is None:
        raise HTTPException(status_code=404, detail="Delivery challan not found")

    product_ids = {item.product_id for item in challan.items}
    products = (
        db.query(Product).filter(Product.id.in_(product_ids), Product.company_id == company_id).all()
        if product_ids
        else []
    )
    company = db.query(CompanyProfile).filter(CompanyProfile.id == company_id).first()
    return _build_multi_copy_delivery_challan_html(
        challan,
        products,
        copies,
        show_sku=company.show_sku_on_pdf if company else True,
    )


def render_delivery_challan_pdf(db: Session, company_id: int, challan_id: int, *, copies: int = 1) -> BytesIO:
    html = build_delivery_challan_html(db, company_id, challan_id, copies=copies)
    return BytesIO(weasyprint.HTML(string=html, url_fetcher=safe_url_fetcher).write_pdf())
