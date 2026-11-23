import pytest

from src.models.company import CompanyProfile


@pytest.mark.parametrize("currency,expected", [(None, "INR"), ("", "INR"), ("  ", "INR"), ("INR", "INR"), ("USD", "USD")])
def test_all_analytics_reports_use_the_company_currency_or_inr(client, db_session, currency, expected):
    assert client.get("/api/company/").status_code == 200
    company = db_session.query(CompanyProfile).first()
    company.currency_code = currency
    db_session.commit()
    product = client.post("/api/products/", json={"name": "Currency widget", "price": 100, "gst_rate": 18}).json()

    for endpoint in ("sales-by-month", "sales-by-product", "profit-loss", "product-performance", f"product-performance/{product['id']}"):
        response = client.get(f"/api/analytics/{endpoint}", params={"from_date": "2026-04-01", "to_date": "2026-04-30"})
        assert response.status_code == 200, response.text
        assert response.json()["currency_code"] == expected, endpoint
