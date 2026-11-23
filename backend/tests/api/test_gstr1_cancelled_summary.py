from datetime import timedelta

import pytest

from src.models.credit_note import CreditNote
from tests.api.test_gstr1_filing_edges import (
    _export, _note, _sale, _summary, seller,  # noqa: F401 -- seller fixture
)
from tests.api.test_product_performance import _create_ledger, _create_product, _line


@pytest.mark.parametrize("cancelled", [0, 1, 3])
def test_screen_counts_reconcile_with_table_13_without_cancelled_tax(client, seller, db_session, cancelled):
    product = _create_product(client, "SUMMARY", "Widget", hsn_sac="8471")
    customer = _create_ledger(client, "Walk-in")
    sale = _sale(client, customer, product, items=[_line(product, 5, 1000)])
    notes = [_note(client, [sale]) for _ in range(4)]
    for note in notes[:cancelled] + notes[3:]:
        response = client.post(f"/api/credit-notes/{note['id']}/cancel")
        assert response.status_code == 200, response.text
    # A cancelled note from a different period must not enter this summary.
    older = db_session.get(CreditNote, notes[3]['id'])
    older.credit_note_date -= timedelta(days=40)
    db_session.commit()
    cancelled_sale = _sale(client, customer, product)
    response = client.delete(f"/api/invoices/{cancelled_sale['id']}")
    assert response.status_code == 200, response.text

    summary = _summary(client)
    exported = _export(client)
    docs = summary['doc_summary']
    table13 = {row['doc_num']: row['docs'] for row in exported['doc_issue']['doc_det']}
    for number, active_key, cancelled_key in (
        (1, 'total_invoices', 'cancelled_invoices'),
        (5, 'total_credit_notes', 'cancelled_credit_notes'),
    ):
        assert docs[active_key] == sum(row['net_issue'] for row in table13[number])
        assert docs[cancelled_key] == sum(row['cancel'] for row in table13[number])
        assert docs[active_key] + docs[cancelled_key] == sum(row['totnum'] for row in table13[number])
    assert docs['cancelled_credit_notes'] == cancelled
    assert docs['cancelled_invoices'] == 1
    assert summary['credit_notes']['invoice_count'] == 3 - cancelled
    assert summary['credit_notes']['taxable_value'] == (3 - cancelled) * 1000
    assert sum(row['txval'] for row in exported['b2cs']) == (2 + cancelled) * 1000
