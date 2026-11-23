import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import type { Invoice } from '../types/api';
import InvoicePreview from './InvoicePreview';

vi.mock('../context/AuthContext', () => ({ useAuth: () => ({ isAdmin: false }) }));

function preview(status: Invoice['status'], voucher_type: Invoice['voucher_type']) {
  const invoice = {
    id: 1, invoice_number: 'INV-000001', invoice_date: '2026-11-23',
    status, voucher_type, total_amount: 100, paid_amount: 0,
  } as Invoice;
  return renderToStaticMarkup(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <InvoicePreview invoice={invoice} onClose={() => {}} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('invoice preview delivery actions', () => {
  it.each(['sales', 'purchase'] as const)('keeps active %s sharing and email available', (kind) => {
    const html = preview('active', kind);
    expect(html).toContain('title="Share a link to this invoice"');
    expect(html).toContain('title="Email invoice"');
    expect(html.match(/title="Download invoice PDF"/g)).toHaveLength(1);
    expect(html).toContain('title="Print invoice"');
  });

  it.each(['sales', 'purchase'] as const)('offers download and print for cancelled %s invoices', (kind) => {
    const html = preview('cancelled', kind);
    expect(html).not.toContain('title="Share a link to this invoice"');
    expect(html).not.toContain('title="Email invoice"');
    expect(html.match(/title="Download invoice PDF"/g)).toHaveLength(1);
    expect(html).toContain('title="Print invoice"');
  });
});
