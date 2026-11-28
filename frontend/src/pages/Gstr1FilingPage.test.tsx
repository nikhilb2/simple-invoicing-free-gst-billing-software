import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { StaticRouter } from 'react-router-dom/server';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Gstr1FilingPage, { Gstr1ValidationIssues } from './Gstr1FilingPage';
import type { Gstr1ValidationError } from '../types/api';

vi.mock('../context/FYContext', () => ({
  useFY: () => ({ activeFY: { start_date: '2026-04-01', end_date: '2027-03-31' } }),
}));

afterEach(() => vi.useRealTimers());

describe('Gstr1FilingPage', () => {
  it('offers only month and quarter filing presets, even when a financial year is active', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 10, 15));
    const client = new QueryClient();
    try {
      const html = renderToStaticMarkup(
        <QueryClientProvider client={client}>
          <StaticRouter location="/gstr1"><Gstr1FilingPage /></StaticRouter>
        </QueryClientProvider>,
      );
      const labels = [...html.matchAll(/<button[^>]*class="scope-preset[^"]*"[^>]*>([^<]+)<\/button>/g)]
        .map((match) => match[1]);
      expect(labels).toEqual(['Last month', 'This month', 'Last quarter', 'This quarter']);
      expect(html).toMatch(/aria-pressed="true"[^>]*>Last month<\/button>/);
    } finally {
      client.clear();
    }
  });

  describe('validation issues', () => {
    const missingGstin: Gstr1ValidationError = {
      invoice_number: '',
      field: 'Company GSTIN',
      message: 'Company GSTIN is required to generate GSTR-1 export. Please set your company GSTIN in Settings.',
      severity: 'error',
    };
    const invoiceIssue: Gstr1ValidationError = {
      invoice_number: 'INV-7',
      field: 'HSN',
      message: 'HSN code is missing.',
      severity: 'error',
    };
    const render = (errors: Gstr1ValidationError[]) => renderToStaticMarkup(
      <StaticRouter location="/gstr1"><Gstr1ValidationIssues errors={errors} /></StaticRouter>,
    );

    it('shows a missing company GSTIN above the table, with a link to company settings', () => {
      const html = render([missingGstin, invoiceIssue]);
      const callout = html.indexOf('<div class="form-error" role="alert">');
      expect(callout).toBeGreaterThanOrEqual(0);
      expect(callout).toBeLessThan(html.indexOf('<table'));
      expect(html).toContain(
        '<a class="link-button link-button--tap" href="/settings/company?focus=gstin">Open company settings →</a>',
      );
      // The table keeps the invoice rows but no longer repeats the company GSTIN row.
      expect(html).toContain('INV-7');
      expect(html.slice(html.indexOf('<table'))).not.toContain('Company GSTIN');
    });

    it('hides the table and the all-clear when the company GSTIN is the only issue', () => {
      const html = render([missingGstin]);
      expect(html).toContain('Open company settings →');
      expect(html).not.toContain('<table');
      expect(html).not.toContain('No issues found');
    });

    it('keeps the all-clear when there are no issues, and invoice rows without a callout', () => {
      expect(render([])).toContain('No issues found');
      const html = render([invoiceIssue]);
      expect(html).toContain('<table');
      expect(html).not.toContain('form-error');
    });
  });
});
