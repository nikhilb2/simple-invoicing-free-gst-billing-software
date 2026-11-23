from datetime import datetime

from sqlalchemy.orm import Session

from src.models.company import CompanyProfile
from src.models.company_account import CompanyAccount


def seed_default_cash_account(
    db: Session,
    company: CompanyProfile,
    created_by: int | None = None,
) -> CompanyAccount | None:
    """Give a new company a "Cash" account.

    Without any account, the receipt forms could only file a payment as
    Unallocated, and the Cash & Bank register had nowhere to show it. The forms
    preselect this account, so a new company's first receipts land in it.
    Does nothing when the company already has an account. Flushes, but does not
    commit: the caller owns the transaction.
    """
    existing = db.query(CompanyAccount.id).filter(CompanyAccount.company_id == company.id).first()
    if existing is not None:
        return None
    account = CompanyAccount(
        company_id=company.id,
        account_type="cash",
        display_name="Cash",
        display_on_invoice=False,
        opening_balance=0,
        is_active=True,
        created_by=created_by,
        updated_at=datetime.utcnow(),
    )
    db.add(account)
    db.flush()
    return account
