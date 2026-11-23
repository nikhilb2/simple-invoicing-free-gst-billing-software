import csv
import io
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from itsdangerous import BadSignature, URLSafeTimedSerializer
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.api.deps import get_active_company, require_company_role
from src.core.analytics import distinct_id_for, track
from src.core.config import settings
from src.core.document_limits import MONEY_LIMIT, QUANTITY_LIMIT
from src.core.validation import hsn_sac_warning, normalize_hsn_sac
from src.db.session import get_db
from src.models.company import CompanyProfile
from src.models.inventory import Inventory
from src.models.product import Product
from src.models.product_bulk_update import ProductBulkUpdate
from src.models.user import User, UserRole

router = APIRouter()
editor = require_company_role(UserRole.admin, UserRole.manager)
signer = URLSafeTimedSerializer(settings.SECRET_KEY, salt="product-bulk-update-v1")
MAX_BYTES = 1024 * 1024
MAX_EDITS = 500
PRICE_FIELDS = {"Purchase Price": "purchase_price", "Selling Price": "price"}
COLUMNS = (
    "Product ID", "Product Name", "Purchase Price", "Purchase Price GST",
    "Selling Price", "Selling Price GST", "HSN/SAC", "Current Stock", "Replacement Stock",
)


def catalogue(db: Session, company_id: int):
    return db.query(Product).filter(Product.company_id == company_id)


def stock_rows(db: Session, company_id: int, ids: list[int], *, lock: bool = False):
    query = db.query(Inventory).filter(
        Inventory.company_id == company_id, Inventory.product_id.in_(ids)
    ).order_by(Inventory.product_id)
    if lock:
        query = query.with_for_update()
    return {row.product_id: row for row in query}


def displayed_name(name: str) -> str:
    # A text prefix protects formula-looking names in spreadsheet applications.
    return f"Name: {name}"


def unprefixed(name: str) -> str:
    name = name.strip()
    if name[:5].casefold() == "name:":
        name = name[5:]
    return name.strip().casefold()


@router.get("/export")
def export_bulk_update(
    db: Session = Depends(get_db),
    _: User = Depends(editor),
    company: CompanyProfile = Depends(get_active_company),
):
    products = catalogue(db, company.id).order_by(Product.id).all()
    inventory = stock_rows(db, company.id, [product.id for product in products])
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(COLUMNS)
    for product in products:
        stock = inventory.get(product.id)
        writer.writerow([
            product.id, displayed_name(product.name), product.purchase_price, "Exclusive",
            product.price, "Exclusive", f"HSN:{product.hsn_sac}" if product.hsn_sac else "",
            stock.quantity if stock else "", "",
        ])
    return Response(
        buffer.getvalue().encode("utf-8-sig"),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="bulk-product-update.csv"'},
    )


def number(value: str, places: int, limit: int) -> Decimal:
    if not re.fullmatch(rf"[0-9]{{1,12}}(?:\.[0-9]{{1,{places}}})?", value):
        raise ValueError(f"Enter a non-negative number with at most {places} decimal places")
    result = Decimal(value)
    if result >= limit:
        raise ValueError(f"Value must be below {limit:,}")
    return result


def current_value(product: Product, stock: Inventory | None, field: str):
    if field == "stock":
        return format(stock.quantity, ".3f") if stock else None
    value = getattr(product, field)
    return format(value, ".2f") if field in PRICE_FIELDS.values() else value


def row_changes(row: dict, product: Product, stock: Inventory | None) -> dict:
    proposed = {}
    for column, field in PRICE_FIELDS.items():
        if not row[column]:
            continue
        price = number(row[column], 2, MONEY_LIMIT)
        basis = row[f"{column} GST"].casefold()
        if basis == "inclusive":
            price = (price / (1 + product.gst_rate / 100)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        elif basis != "exclusive":
            raise ValueError(f"{column} GST must be Inclusive or Exclusive")
        proposed[field] = format(price, ".2f")

    code = row["HSN/SAC"]
    if code[:4].casefold() == "hsn:":
        code = code[4:].strip()
    if row["HSN/SAC"] and code != product.hsn_sac:
        hsn = normalize_hsn_sac(code)
        if not hsn:
            raise ValueError("Enter an HSN/SAC code after HSN:")
        warning = hsn_sac_warning(hsn)
        if warning:
            raise ValueError(warning)
        proposed["hsn_sac"] = hsn

    if row["Replacement Stock"]:
        quantity = number(row["Replacement Stock"], 3, QUANTITY_LIMIT)
        if not product.maintain_inventory or product.track_serials:
            raise ValueError("Stock replacement requires inventory tracking without serial numbers")
        if not product.allow_decimal and quantity != quantity.to_integral_value():
            raise ValueError("Stock must be a whole number for this product")
        proposed["stock"] = format(quantity, ".3f")

    changes = {}
    for field, new in proposed.items():
        old = current_value(product, stock, field)
        if new != old and not (field == "stock" and old is None and Decimal(new) == 0):
            changes[field] = {"old": old, "new": new}
    return changes


def snapshot(product: Product) -> list:
    return [
        product.name, format(product.gst_rate, ".2f"), product.maintain_inventory,
        product.track_serials, product.allow_decimal,
    ]


@router.post("/preview")
def preview_bulk_update(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(editor),
    company: CompanyProfile = Depends(get_active_company),
):
    content = file.file.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise HTTPException(413, "CSV must be 1 MB or smaller")
    products = catalogue(db, company.id).all()
    by_id = {str(product.id): product for product in products}
    by_name = defaultdict(list)
    for product in products:
        by_name[product.name.strip().casefold()].append(product)
    inventory = stock_rows(db, company.id, [product.id for product in products])
    errors, changes, seen = [], [], set()
    try:
        reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig"), newline=""), strict=True)
        if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise ValueError("CSV needs a header with unique column names")
        if set(reader.fieldnames) - set(COLUMNS) or not set(reader.fieldnames) & {"Product ID", "Product Name"}:
            raise ValueError("Use the headers from the bulk update CSV export")

        for cells in reader:
            line = reader.line_num
            try:
                if None in cells:
                    raise ValueError("Row has extra cells")
                row = {name: (cells.get(name) or "").strip() for name in COLUMNS}
                if not any(row.values()):
                    continue
                if row["Product ID"]:
                    product = by_id.get(row["Product ID"])
                    if product is None:
                        raise ValueError("Unknown product ID")
                    if row["Product Name"] and unprefixed(row["Product Name"]) != product.name.strip().casefold():
                        raise ValueError("Product name does not match the product ID")
                else:
                    name = unprefixed(row["Product Name"])
                    matches = by_name.get(name, [])
                    if len(matches) != 1:
                        raise ValueError("Product name must match exactly one product")
                    product = matches[0]
                if product.id in seen:
                    raise ValueError("Duplicate product")
                seen.add(product.id)
                fields = row_changes(row, product, inventory.get(product.id))
                if fields:
                    changes.append({
                        "id": product.id, "name": product.name, "fields": fields,
                        "snapshot": snapshot(product),
                    })
            except ValueError as exc:
                errors.append({"row": line, "message": str(exc)})
                if len(errors) >= 100:
                    break
        if len(changes) > MAX_EDITS:
            raise ValueError(f"Update up to {MAX_EDITS} products in one file")
    except (UnicodeError, csv.Error, ValueError) as exc:
        raise HTTPException(400, f"Invalid CSV: {exc}") from exc

    token = None
    if changes and not errors:
        token = signer.dumps({
            "id": uuid4().hex, "company": company.id, "user": user.id, "changes": changes,
        })
    return {"changes": changes, "errors": errors, "token": token}


class BulkConfirmation(BaseModel):
    token: str = Field(max_length=1_400_000)
    confirm_stock: bool = False


@router.post("/confirm")
def confirm_bulk_update(
    payload: BulkConfirmation,
    db: Session = Depends(get_db),
    user: User = Depends(editor),
    company: CompanyProfile = Depends(get_active_company),
):
    try:
        preview, issued_at = signer.loads(payload.token, return_timestamp=True)
    except BadSignature as exc:
        raise HTTPException(400, "Preview is invalid or expired. Preview the CSV again.") from exc
    if preview["company"] != company.id or preview["user"] != user.id:
        raise HTTPException(403, "Preview belongs to a different company or user")

    changes = preview["changes"]
    ids = [change["id"] for change in changes]
    stock_ids = [change["id"] for change in changes if "stock" in change["fields"]]
    if stock_ids and not payload.confirm_stock:
        raise HTTPException(400, "Confirm stock replacement separately")

    if db.get(ProductBulkUpdate, preview["id"]):
        return {"updated": len(changes)}
    if datetime.now(timezone.utc) - issued_at > timedelta(minutes=30):
        raise HTTPException(400, "Preview expired. Preview the CSV again.")
    products = {
        product.id: product for product in catalogue(db, company.id)
        .filter(Product.id.in_(ids)).order_by(Product.id).with_for_update()
    }
    # A retry may have waited for the original request's product locks.
    if db.get(ProductBulkUpdate, preview["id"]):
        return {"updated": len(changes)}
    inventory = stock_rows(db, company.id, stock_ids, lock=True) if stock_ids else {}

    for change in changes:
        product = products.get(change["id"])
        stock = inventory.get(change["id"])
        if product is None or snapshot(product) != change["snapshot"] or any(
            current_value(product, stock, field) != values["old"]
            for field, values in change["fields"].items()
        ):
            raise HTTPException(409, "Catalogue values changed. Preview the CSV again.")

    for change in changes:
        product = products[change["id"]]
        for field, values in change["fields"].items():
            if field == "stock":
                stock = inventory.get(product.id)
                if stock is None:
                    stock = Inventory(company_id=company.id, product_id=product.id)
                    db.add(stock)
                stock.quantity = Decimal(values["new"])
            else:
                setattr(product, field, values["new"] if field == "hsn_sac" else Decimal(values["new"]))
    db.add(ProductBulkUpdate(
        id=preview["id"], company_id=company.id, user_id=user.id, changes=changes,
    ))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if db.get(ProductBulkUpdate, preview["id"]):
            return {"updated": len(changes)}
        raise HTTPException(409, "Catalogue or stock changed. Preview the CSV again.") from exc
    track(
        "products_bulk_updated",
        distinct_id_for(user),
        {"product_count": len(changes), "stock_count": len(stock_ids)},
    )
    return {"updated": len(changes)}
