"""The per-test cleanup of the Postgres schema leaves no rows and restarts ids.

Every test in this directory starts from :func:`clean_rls_db`; if it left a row
behind or an id counting on, tests would see each other's data.
"""

from datetime import datetime, timezone

from sqlalchemy import func, select, text

from src.db.base import Base
from src.models.company import CompanyProfile
from src.models.company_membership import CompanyMembership
from src.models.user import User, UserRole


def _seed(session_factory) -> None:
    with session_factory() as owner:
        user = User(
            email="alice@alpha.example",
            full_name="Alice",
            hashed_password="not-a-real-hash",
            role=UserRole.admin,
            email_verified_at=datetime.now(timezone.utc),
        )
        company = CompanyProfile(name="Alpha Traders", address="1 Market Road")
        owner.add_all([user, company])
        owner.flush()
        owner.add(CompanyMembership(user_id=user.id, company_id=company.id, role=UserRole.admin))
        owner.commit()


def _row_counts(db) -> dict[str, int]:
    with db.owner_engine.connect() as conn:
        return {
            table.name: conn.execute(select(func.count()).select_from(table)).scalar_one()
            for table in Base.metadata.sorted_tables
        }


def test_emptying_the_schema_removes_every_row_and_restarts_ids(clean_rls_db, empty_tables):
    _seed(clean_rls_db.OwnerSession)
    seeded = {name: n for name, n in _row_counts(clean_rls_db).items() if n}
    assert seeded, "the seed wrote nothing, so this test would prove nothing"

    empty_tables()

    assert {name: n for name, n in _row_counts(clean_rls_db).items() if n} == {}
    _seed(clean_rls_db.OwnerSession)
    with clean_rls_db.owner_engine.connect() as conn:
        assert conn.execute(text("SELECT id FROM users")).scalar_one() == 1
        assert conn.execute(text("SELECT id FROM company_profiles")).scalar_one() == 1
