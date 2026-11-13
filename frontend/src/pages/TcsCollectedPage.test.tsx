import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import TcsCollectedPage, { TcsCollectedView, returnNote, taxYearLabel } from './TcsCollectedPage';
import type { TcsReport } from '../api/tcsReports';

const report: TcsReport = {
  tax_year: 2026,
  quarter: 1,
  from_date: '2026-04-01',
  to_date: '2026-06-30',
  return_form: 'Form 143',
  rows: [
    {
      kind: 'invoice', id: 1, document_number: 'INV/26 #1', date: '2026-04-15', invoice_number: 'INV/26 #1',
      buyer_name: 'Scrap Buyer', buyer_pan: 'ABCDE1234F', section_ref: '394(1) Sl. No. 4',
      nature: 'Scrap', base_amount: '236000.00', rate: '1.0000', tcs_amount: '2360.00',
    },
    {
      kind: 'credit_note', id: 3, document_number: 'CN-3', date: '2026-05-02', invoice_number: 'INV/26 #1',
      buyer_name: 'Scrap Buyer', buyer_pan: null, section_ref: '394(1) Sl. No. 4',
      nature: 'Scrap', base_amount: '-59000.00', rate: '1.0000', tcs_amount: '-590.00',
    },
  ],
  totals_by_section: [
    { section_ref: '394(1) Sl. No. 4', nature: 'Scrap', count: 2, base_amount: '177000.00', tcs_amount: '1770.00' },
  ],
  total_base: '177000.00',
  total_tcs: '1770.00',
};

describe('TcsCollectedPage', () => {
  it('offers the filters and a CSV export held back until there is a report', () => {
    const html = renderToStaticMarkup(
      <QueryClientProvider client={new QueryClient()}><TcsCollectedPage /></QueryClientProvider>,
    );
    expect(html).toContain('Tax year');
    expect(html).toContain('All quarters');
    expect(html).toContain('Q4 (Jan-Mar)');
    expect(html).toMatch(/<button[^>]*disabled[^>]*>Export CSV/);
  });

  it('labels tax years', () => {
    expect(taxYearLabel(2026)).toBe('2026-27');
  });
});

describe('TcsCollectedView', () => {
  it('shows rows, marks credit notes and shows net totals', () => {
    const html = TcsCollectedViewHtml();
    expect(html).toContain('INV/26 #1');
    expect(html).toContain('Credit note');
    expect(html).toContain('No PAN');
    expect(html).toContain('2,360.00');
    expect(html).toContain('1,770.00');
    expect(html).toContain('1,77,000.00');
    expect(html).toContain('Grand total');
  });

  it('names the return the figures feed', () => {
    expect(TcsCollectedViewHtml()).toContain('Form 143');
    expect(returnNote('Form 27EQ')).toContain('Form 27EQ');
  });
});

function TcsCollectedViewHtml() {
  return renderToStaticMarkup(<TcsCollectedView report={report} />);
}

describe('sales with no TCS collected', () => {
  it('flags a declaration row and notes the amount sold without TCS', () => {
    const html = renderToStaticMarkup(
      <TcsCollectedView
        report={{
          ...report,
          rows: [{ ...report.rows[0], id: 9, tcs_amount: '0.00', remark: 'Declaration – not collected' }],
          totals_by_section: [{ ...report.totals_by_section[0], not_collected_base: '118000.00' }],
        }}
      />,
    );
    expect(html).toContain('Declaration – not collected');
    expect(html).toContain('sold with no TCS collected');
  });
});
