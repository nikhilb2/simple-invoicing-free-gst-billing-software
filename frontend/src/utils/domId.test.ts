import { describe, expect, it } from 'vitest';
import { domIdPart } from './domId';

describe('domIdPart', () => {
  it('turns a section title into an id with no spaces', () => {
    expect(domIdPart('Allocate against invoices')).toBe('allocate-against-invoices');
    expect(`allocation-${domIdPart('Edit invoice allocations')}-4-tds-section`).toBe('allocation-edit-invoice-allocations-4-tds-section');
  });
  it('drops punctuation at the ends', () => {
    expect(domIdPart('  Receipt / Payment! ')).toBe('receipt-payment');
  });
});
