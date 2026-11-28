import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, test, vi } from 'vitest';
import DueInvoiceRow from './DueInvoiceRow';
import type { Invoice } from '../types/api';

function invoice(overrides: Partial<Invoice>): Invoice {
  return {
    id: 12,
    invoice_number: 'INV-2026-012',
    voucher_type: 'sales',
    status: 'active',
    payment_status: 'partial',
    total_amount: 1113,
    paid_amount: 500,
    tds_amount: 0,
    outstanding_amount: 613,
    invoice_date: '2026-11-12',
    due_date: '2026-11-20',
    due_in_days: -8,
    ledger_id: 7,
    ledger_name: 'Demo Traders',
    ledger_phone: '98765 43210',
    items: [],
    ...overrides,
  } as Invoice;
}

function render(inv: Invoice) {
  return renderToStaticMarkup(
    <MemoryRouter>
      <DueInvoiceRow invoice={inv} currencyCode="INR" onPreview={vi.fn()} onRecordPayment={vi.fn()} />
    </MemoryRouter>,
  );
}

describe('DueInvoiceRow', () => {
  test('the big number is the amount due, not the bill total', () => {
    const html = render(invoice({}));
    expect(html).toContain('<span class="invoice-row__price">₹613.00 due</span>');
    expect(html).not.toMatch(/invoice-row__price">[^<]*1,113/);
    expect(html).toContain('Bill ₹1,113.00');
    expect(html).toContain('₹500.00 received');
  });

  test('leads with the customer, a link to the customer page', () => {
    const html = render(invoice({}));
    expect(html.indexOf('Demo Traders')).toBeLessThan(html.indexOf('INV-2026-012'));
    expect(html).toContain('href="/ledgers/7"');
    expect(html).toContain('INV-2026-012 · due ');
  });

  test('an unpaid row shows only the bill, and no raw status words', () => {
    const html = render(invoice({ payment_status: 'unpaid', paid_amount: 0, total_amount: 52.5, outstanding_amount: 52.5 }));
    expect(html).toContain('Bill ₹52.50');
    expect(html).not.toMatch(/Bill[^<]*received/);
    for (const word of ['partial', 'unpaid', 'Remaining', 'Status', 'Record payment', 'Ledger<']) {
      expect(html).not.toContain(word);
    }
  });

  test('with a phone: labelled primary Remind on WhatsApp to wa.me/<number>, no hint', () => {
    const html = render(invoice({}));
    expect(html).toContain('button--primary');
    expect(html).toContain('>Remind on WhatsApp<');
    expect(html).toContain('href="https://wa.me/919876543210?text=');
    expect(html).toContain('aria-label="WhatsApp reminder to Demo Traders"');
    expect(html).not.toContain('No phone number saved');
    expect(html).not.toContain('Add phone number');
  });

  test('without a phone: same button to wa.me/?text=, a hint and an Add phone number link', () => {
    const html = render(invoice({ ledger_phone: null, ledger_name: 'Walk-in Ramesh' }));
    expect(html).toContain('>Remind on WhatsApp<');
    expect(html).toContain('href="https://wa.me/?text=');
    expect(html).toContain('No phone number saved. WhatsApp will ask you to choose the contact.');
    expect(html).toContain('link-button--tap');
    expect(html).toMatch(/href="\/ledgers\/7"[^>]*>Add phone number</);
  });

  test('Payment received and View bill, named for the invoice', () => {
    const html = render(invoice({}));
    expect(html).toContain('aria-label="Payment received for invoice INV-2026-012"');
    expect(html).toContain('>Payment received<');
    expect(html).toContain('>View bill<');
  });

  test('a not-yet-overdue bill shows the due-in badge and no overdue badge', () => {
    const html = render(invoice({ due_in_days: 3, due_date: '2026-12-01' }));
    expect(html).toContain('Due in 3 days');
    expect(html).not.toContain('overdue-badge');
  });
});
