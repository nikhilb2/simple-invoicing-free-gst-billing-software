import { describe, expect, it } from 'vitest';
import { hasComposerDocumentParam, isFirstRun, showBillTypeRow } from './getStarted';

const base = { hasInvoice: false, urlPicksDocument: false, voucherType: 'sales', locked: false, changeChosen: false } as const;

describe('isFirstRun', () => {
  it('is true only when the company is known to have no invoice', () => {
    expect(isFirstRun(false)).toBe(true);
    expect(isFirstRun(true)).toBe(false);
  });

  it('is not a first run while loading or if the lookup failed', () => {
    expect(isFirstRun(undefined)).toBe(false);
    expect(isFirstRun(null)).toBe(false);
  });
});

describe('hasComposerDocumentParam', () => {
  it.each(['new', 'edit', 'duplicate', 'edit_quotation', 'from_quotation', 'from_challan'])('%s picks a document', (key) => {
    expect(hasComposerDocumentParam(new URLSearchParams(`${key}=1`))).toBe(true);
  });

  it('ignores params that pick nothing', () => {
    expect(hasComposerDocumentParam(new URLSearchParams(''))).toBe(false);
    expect(hasComposerDocumentParam(new URLSearchParams('add=product'))).toBe(false);
    expect(hasComposerDocumentParam(new URLSearchParams('add=customer'))).toBe(false);
  });
});

describe('showBillTypeRow', () => {
  it('shows the row for a plain new sales invoice in a company with no invoice', () => {
    expect(showBillTypeRow(base)).toBe(true);
  });

  it('shows today\'s dropdown while the answer is unknown', () => {
    expect(showBillTypeRow({ ...base, hasInvoice: undefined })).toBe(false);
    expect(showBillTypeRow({ ...base, hasInvoice: null })).toBe(false);
  });

  it('shows the dropdown once the company has an invoice', () => {
    expect(showBillTypeRow({ ...base, hasInvoice: true })).toBe(false);
  });

  it('shows the dropdown when the URL picked a document', () => {
    expect(showBillTypeRow({ ...base, urlPicksDocument: true })).toBe(false);
  });

  it('shows the dropdown for a preselected or locked voucher type', () => {
    expect(showBillTypeRow({ ...base, voucherType: 'quotation' })).toBe(false);
    expect(showBillTypeRow({ ...base, voucherType: 'purchase' })).toBe(false);
    expect(showBillTypeRow({ ...base, locked: true })).toBe(false);
  });

  it('keeps the dropdown after Change', () => {
    expect(showBillTypeRow({ ...base, changeChosen: true })).toBe(false);
  });
});
