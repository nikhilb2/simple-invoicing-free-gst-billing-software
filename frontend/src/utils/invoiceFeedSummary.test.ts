import { describe, expect, test } from 'vitest';
import { invoiceFeedSummaryLine, isInvoiceFeedFiltered } from './invoiceFeedSummary';

describe('invoiceFeedSummaryLine', () => {
  test('shows Sales, Purchases and the financial year', () => {
    expect(invoiceFeedSummaryLine({ debit: 10080, credit: 157.5 }, 'INR', '2026-27', false)).toBe(
      'Sales ₹10,080.00 · Purchases ₹157.50 · 2026-27',
    );
  });

  test('leaves out Purchases when it is zero', () => {
    expect(invoiceFeedSummaryLine({ debit: 630, credit: 0 }, 'INR', '2026-27', false)).toBe('Sales ₹630.00 · 2026-27');
  });

  test('adds "filtered" when a search or filter is active', () => {
    expect(invoiceFeedSummaryLine({ debit: 630, credit: 0 }, 'INR', '2026-27', true)).toBe('Sales ₹630.00 · 2026-27 · filtered');
  });

  test('drops the year when searching all financial years', () => {
    expect(invoiceFeedSummaryLine({ debit: 630, credit: 157.5 }, 'INR', null, true)).toBe('Sales ₹630.00 · Purchases ₹157.50 · filtered');
  });
});

describe('isInvoiceFeedFiltered', () => {
  test('is false with no search, filter or product', () => {
    expect(isInvoiceFeedFiltered('', 0, null)).toBe(false);
    expect(isInvoiceFeedFiltered('   ', 0, null)).toBe(false);
  });

  test('is true for a search, a filter or a product filter', () => {
    expect(isInvoiceFeedFiltered('mehta', 0, null)).toBe(true);
    expect(isInvoiceFeedFiltered('', 2, null)).toBe(true);
    expect(isInvoiceFeedFiltered('', 0, 5)).toBe(true);
  });
});
