import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, test, vi } from 'vitest';
import InvoicesCompactCard from './InvoicesCompactCard';
import InvoicesTotalBreakdown from './InvoicesTotalBreakdown';
import type { Invoice } from '../types/api';

function invoice(voucherType: 'sales' | 'purchase'): Invoice {
  return {
    id: 1,
    invoice_number: 'INV-1',
    voucher_type: voucherType,
    status: 'active',
    payment_status: 'unpaid',
    outstanding_amount: 500,
    total_amount: 500,
    total_tax_amount: 0,
    invoice_date: '2026-11-01',
    due_date: '2026-11-01',
    ledger_id: 7,
    ledger: null,
    items: [],
  } as unknown as Invoice;
}

const breakdown = { credit: 20, debit: 30, cancelled: 5, total: 55 };

describe('Invoice Feed amount labels', () => {
  test('bill cards say Bill total for both sales and purchases', () => {
    for (const kind of ['sales', 'purchase'] as const) {
      const html = renderToStaticMarkup(
        <InvoicesCompactCard
          invoice={invoice(kind)}
          currencyCode="INR"
          onPreview={vi.fn()}
        />,
      );
      expect(html).toContain('Bill total');
      expect(html).not.toContain('Debit (Sales)');
      expect(html).not.toContain('Credit (Purchase)');
    }
  });

  test('summary panel uses plain words in the specified order', () => {
    const html = renderToStaticMarkup(
      <InvoicesTotalBreakdown breakdown={breakdown} currencyCode="INR" />,
    );
    const labels = [
      'Sales',
      'Purchases',
      'Cancelled',
      'All bills (incl. cancelled)',
      'All bills (not cancelled)',
    ];
    let previous = -1;
    for (const label of labels) {
      const at = html.indexOf(label);
      expect(at, `missing label: ${label}`).toBeGreaterThan(-1);
      expect(at, `out of order: ${label}`).toBeGreaterThan(previous);
      previous = at;
    }
    expect(html).not.toContain('Total Listed');
    expect(html).not.toContain('Active Total');
    expect(html).not.toContain('Debit (Sales)');
    expect(html).not.toContain('Credit (Purchase)');
  });
});
