import { afterAll, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { renderToString } from 'react-dom/server';
import TaxInclusiveToggle from './TaxInclusiveToggle';
import { PRICE_INCLUDES_GST_LABEL, priceColumnLabel, priceIncludesGstExample } from '../utils/invoiceTotals';

vi.hoisted(() => { vi.stubGlobal('localStorage', { getItem: () => null }); });
afterAll(() => vi.unstubAllGlobals());

const format = (v: number) => `Rs ${v.toLocaleString('en-IN')}`;

describe('priceIncludesGstExample', () => {
  it('ticked: splits the typed price into taxable value and GST', () => {
    expect(priceIncludesGstExample({ unitPrice: 1180, gstRate: 18, taxInclusive: true, format }))
      .toBe('Price Rs 1,180 with 18% GST = Rs 1,000 taxable value + Rs 180 GST');
  });
  it('unticked: adds GST on top of the typed price', () => {
    expect(priceIncludesGstExample({ unitPrice: 1000, gstRate: 18, taxInclusive: false, format }))
      .toBe('Price Rs 1,000 + Rs 180 GST = Rs 1,180 total');
  });
  it('is hidden without a price or without a GST rate', () => {
    expect(priceIncludesGstExample({ unitPrice: 0, gstRate: 18, taxInclusive: true, format })).toBeNull();
    expect(priceIncludesGstExample({ unitPrice: 1000, gstRate: 0, taxInclusive: false, format })).toBeNull();
    expect(priceIncludesGstExample({ unitPrice: Number.NaN, gstRate: 18, taxInclusive: false, format })).toBeNull();
  });
  it('uses Indian grouping through formatCurrency-style formatters', () => {
    expect(priceIncludesGstExample({ unitPrice: 118000, gstRate: 18, taxInclusive: true, format }))
      .toContain('Rs 1,00,000 taxable value');
  });
});

describe('labels', () => {
  it('names the column by what the user types', () => {
    expect(priceColumnLabel(true)).toBe('Price (incl. GST)');
    expect(priceColumnLabel(false)).toBe('Price');
  });
});

describe('TaxInclusiveToggle', () => {
  it('renders the new label and the example when there is one', () => {
    const html = renderToString(<TaxInclusiveToggle id="x" checked onChange={() => {}} example="Price 1 + 2" />);
    expect(html).toContain(PRICE_INCLUDES_GST_LABEL);
    expect(html).toContain('Price 1 + 2');
    expect(html).not.toContain('Prices include GST');
  });
  it('falls back to a short hint with no example', () => {
    const html = renderToString(<TaxInclusiveToggle id="x" checked={false} onChange={() => {}} example={null} />);
    expect(html).toContain('Tick this if the prices you type already include GST.');
  });
});

// Both forms only render their line items after data loads (effects), which renderToString
// cannot run, so check the wiring in the source instead.
describe.each([
  ['composer', './../pages/invoices/InvoicesPageView.tsx'],
  ['quick-create modal', './CreateInvoiceModal.tsx'],
])('%s', (_name, file) => {
  const source = readFileSync(fileURLToPath(new URL(file, import.meta.url)), 'utf8');
  it('uses the shared toggle and column label, with no old wording', () => {
    expect(source).toContain('<TaxInclusiveToggle');
    expect(source).toContain('priceColumnLabel(taxInclusive)');
    expect(source).not.toContain('Prices include GST');
    expect(source).not.toContain('Amount (incl. GST)');
  });
});
