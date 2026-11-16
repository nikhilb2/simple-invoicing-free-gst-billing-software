import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import DeliveryChallansTable from './DeliveryChallansTable';
import type { DeliveryChallan } from '../types/api';

function challan(overrides: Partial<DeliveryChallan> = {}): DeliveryChallan {
  return {
    id: 1,
    challan_number: 'DC-2026-001',
    status: 'open',
    purpose: 'job_work',
    purpose_label: 'Job work',
    challan_date: '2026-11-01',
    financial_year_id: null,
    ledger_id: 3,
    ledger_name: 'Acme & Sons',
    ledger_address: null,
    ledger_gst: null,
    ledger_phone: null,
    company_name: 'Mofna Traders',
    company_address: null,
    company_gst: null,
    company_currency_code: 'INR',
    place_of_supply: null,
    shipping_address: null,
    shipping_address_label: null,
    shipping_address_id: null,
    reference_notes: null,
    terms_text: null,
    taxable_amount: 1200,
    total_tax_amount: 216,
    cgst_amount: 108,
    sgst_amount: 108,
    igst_amount: 0,
    total_amount: 1416,
    age_days: 14,
    invoiced_at: null,
    cancelled_at: null,
    created_at: '2026-11-01T00:00:00',
    updated_at: '2026-11-01T00:00:00',
    items: [],
    invoice_id: null,
    invoice_number: null,
    invoices: [],
    ...overrides,
  };
}

function render(challans: DeliveryChallan[]) {
  return renderToStaticMarkup(
    <MemoryRouter>
      <DeliveryChallansTable challans={challans} onOpen={() => {}} onConvert={() => {}} />
    </MemoryRouter>,
  );
}

describe('DeliveryChallansTable', () => {
  it('shows the columns a shop works from', () => {
    const html = render([challan()]);
    expect(html).toContain('data-testid="delivery-challans-table"');
    expect(html).toContain('data-testid="challan-row-1"');
    expect(html).toContain('DC-2026-001');
    expect(html).toContain('Acme &amp; Sons');
    expect(html).toContain('Job work');
    expect(html).toContain('1,200');
    expect(html).toContain('Open');
    expect(html).toContain('14 days');
  });

  it('values the challan by its taxable amount, not the tax-inclusive total', () => {
    const html = render([challan()]);
    expect(html).not.toContain('1,416');
  });

  it('offers conversion only while the challan is open', () => {
    expect(render([challan()])).toContain('Convert to invoice');
    expect(render([challan({ status: 'invoiced', age_days: null })])).not.toContain('Convert to invoice');
    expect(render([challan({ status: 'cancelled', age_days: null })])).not.toContain('Convert to invoice');
  });

  it('says "1 day", not "1 days"', () => {
    const html = render([challan({ age_days: 1 })]);
    expect(html).toContain('1 day<');
    expect(html).not.toContain('1 days');
  });

  it('lets a long party name break and keeps the Convert button on one line', () => {
    const html = render([challan({ ledger_name: 'fixer-customer-with-a-very-long-unbroken-name' })]);
    expect(html).toMatch(/<td class="delivery-challans-table__party">fixer-customer-with-a-very-long-unbroken-name<\/td>/);
    expect(html).toMatch(/<td class="delivery-challans-table__actions"><button[^>]*aria-label="Convert to invoice"/);
  });

  it('shows a dash for the age once the challan is closed', () => {
    const html = render([challan({ status: 'cancelled', age_days: null })]);
    expect(html).toContain('Cancelled');
    expect(html).not.toContain('days');
  });

  it('links to the live invoice', () => {
    const html = render([challan({
      status: 'invoiced', age_days: null, invoice_id: 9, invoice_number: 'INV-2026-009',
    })]);
    expect(html).toContain('Invoiced');
    expect(html).toContain('INV-2026-009');
    expect(html).toContain('/invoices-view?search=INV-2026-009');
  });

  it('has no payment language anywhere', () => {
    expect(render([challan()])).not.toMatch(/Paid|Unpaid|Due|Balance/);
  });
});
