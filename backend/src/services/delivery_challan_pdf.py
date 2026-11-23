"""Builds and renders the delivery challan PDF."""

from io import BytesIO

from fastapi import HTTPException
from sqlalchemy.orm import Session, selectinload

from src.models.company import CompanyProfile
from src.models.delivery_challan import DeliveryChallan
from src.models.product import Product
from src.services.pdf_paper import Paper, is_thermal, render_pdf
from src.services.pdf_templates.delivery_challan_template import (
    CHALLAN_COPY_LABELS,
    MAX_CHALLAN_COPIES,
    _build_multi_copy_delivery_challan_html,
)
from src.services.pdf_templates.thermal_template import build_thermal_copies, thermal_challan_doc


def build_delivery_challan_html(
    db: Session, company_id: int, challan_id: int, *, copies: int = 1, paper: Paper = "a4"
) -> str | list[str]:
    """The challan for ``paper``: one document for a sheet, one HTML per copy for a roll."""
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
    show_sku = company.show_sku_on_pdf if company else True
    if is_thermal(paper):
        count = max(1, min(MAX_CHALLAN_COPIES, copies))
        return build_thermal_copies(
            [
                thermal_challan_doc(challan, products, copy_label=CHALLAN_COPY_LABELS[i], show_sku=show_sku)
                for i in range(count)
            ],
            paper,
        )
    return _build_multi_copy_delivery_challan_html(challan, products, copies, show_sku=show_sku, paper=paper)


def render_delivery_challan_pdf(
    db: Session, company_id: int, challan_id: int, *, copies: int = 1, paper: Paper = "a4"
) -> BytesIO:
    html = build_delivery_challan_html(db, company_id, challan_id, copies=copies, paper=paper)
    return BytesIO(render_pdf(html, paper))
