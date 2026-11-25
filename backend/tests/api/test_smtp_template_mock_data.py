"""Verify SMTP test email templates render mock amounts with INR currency formatting."""

from __future__ import annotations

import pytest

from src.api.routes.smtp import _TEMPLATE_MOCK_DATA, _jinja_env


@pytest.mark.parametrize(
    ("template_name", "expected_snippets"),
    [
        ("invoice_email", ["\u20b91,25,000.00"]),
        ("payment_reminder", ["\u20b91,25,000.00", "\u20b975,000.00", "\u20b950,000.00"]),
        ("ledger_statement", ["\u20b91,25,000.00", "\u20b91,12,500.00", "\u20b912,500.00"]),
    ],
)
def test_smtp_mock_templates_render_formatted_inr_amounts(
    template_name: str, expected_snippets: list[str]
) -> None:
    template = _jinja_env.get_template(f"{template_name}.html")
    rendered = template.render(**_TEMPLATE_MOCK_DATA[template_name])
    for snippet in expected_snippets:
        assert snippet in rendered
