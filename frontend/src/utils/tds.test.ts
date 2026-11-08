import { describe, expect, it } from 'vitest';
import {
  deductionDate,
  isFullySettled,
  overSettlement,
  purchaseTdsSetting,
  sectionOptionLabel,
  settledAmount,
  showTdsFields,
  totalTds,
  validateTdsAllocations,
} from './tds';
import { validateAllocations } from './validateAllocations';

describe('deductionDate', () => {
  it('takes the earlier of invoice and payment date', () => {
    expect(deductionDate('2026-04-10', '2026-05-01T10:30')).toBe('2026-04-10');
    expect(deductionDate('2026-06-10', '2026-05-01T10:30')).toBe('2026-05-01');
  });
  it('falls back when one is missing', () => {
    expect(deductionDate('2026-04-10', '')).toBe('2026-04-10');
    expect(deductionDate('', '2026-05-01')).toBe('2026-05-01');
  });
});

describe('settledAmount / isFullySettled / overSettlement', () => {
  it('adds in paise', () => {
    expect(settledAmount(0.1, 0.2)).toBe(0.3);
    expect(settledAmount(90000, 10000)).toBe(100000);
  });
  it('detects full settlement', () => {
    expect(isFullySettled(100000, 90000, 10000)).toBe(true);
    expect(isFullySettled(100000, 90000, 5000)).toBe(false);
    expect(isFullySettled(0, 0, 0)).toBe(false);
  });
  it('reports over-settlement', () => {
    expect(overSettlement(100000, 95000, 10000)).toBe(5000);
    expect(overSettlement(100000, 90000, 10000)).toBe(0);
  });
});

describe('totalTds', () => {
  it('sums TDS', () => {
    expect(totalTds([{ tds_amount: 100.1 }, { tds_amount: 0.2 }, {}])).toBe(100.3);
    expect(totalTds(undefined)).toBe(0);
  });
});

describe('validateTdsAllocations', () => {
  const outstanding = [{ id: 1, invoice_number: 'INV-1', remaining_amount: 1000 }];
  it('passes without TDS', () => {
    expect(validateTdsAllocations([{ invoice_id: 1, allocated_amount: 1000 }], outstanding)).toBeNull();
  });
  it('requires a section when TDS is entered', () => {
    expect(validateTdsAllocations([{ invoice_id: 1, invoice_number: 'INV-1', allocated_amount: 900, tds_amount: 100 }], outstanding))
      .toMatch(/TDS section/);
  });
  it('rejects cash + TDS above remaining', () => {
    expect(validateTdsAllocations([{ invoice_id: 1, invoice_number: 'INV-1', allocated_amount: 950, tds_amount: 100, tds_section_id: 5 }], outstanding))
      .toMatch(/exceed/);
  });
  it('accepts cash + TDS equal to remaining', () => {
    expect(validateTdsAllocations([{ invoice_id: 1, allocated_amount: 900, tds_amount: 100, tds_section_id: 5 }], outstanding)).toBeNull();
  });
});

describe('sectionOptionLabel', () => {
  it('formats ref, nature and rate', () => {
    expect(sectionOptionLabel({ section_ref: '393(1) Sl. No. 6(iii)', nature: 'Professional fees', rate_individual_huf: 10, rate_other: 10 }))
      .toBe('s.393(1) Sl. No. 6(iii) — Professional fees (10%)');
  });
  it('shows both rates when they differ', () => {
    expect(sectionOptionLabel({ section_ref: '194C', nature: 'Contractors', rate_individual_huf: 1, rate_other: 2 }))
      .toBe('s.194C — Contractors (1% / 2%)');
  });
  it('omits the rate when unknown', () => {
    expect(sectionOptionLabel({ section_ref: '194C', nature: 'Contractors', rate_individual_huf: null, rate_other: null }))
      .toBe('s.194C — Contractors');
  });
});

describe('validateAllocations with TDS', () => {
  it('does not count TDS towards the payment amount', () => {
    expect(validateAllocations([{ invoice_id: 1, allocated_amount: 900, tds_amount: 100 }], 900)).toBeNull();
  });
  it('allows zero cash only with TDS', () => {
    expect(validateAllocations([{ invoice_id: 1, allocated_amount: 0, tds_amount: 100 }], 500)).toBeNull();
    expect(validateAllocations([{ invoice_id: 1, allocated_amount: 0 }], 500)).toMatch(/greater than 0/);
  });
});

describe('showTdsFields', () => {
  it('always shows on receipts', () => {
    expect(showTdsFields('receipt', false, { tds_amount: 0 })).toBe(true);
  });
  it('shows on payments only when purchase TDS is on', () => {
    expect(showTdsFields('payment', true, { tds_amount: 0 })).toBe(true);
    expect(showTdsFields('payment', false, { tds_amount: 0 })).toBe(false);
    expect(showTdsFields('payment', undefined, undefined)).toBe(false);
  });
  it('keeps existing TDS visible on a payment after the setting is turned off', () => {
    expect(showTdsFields('payment', false, { tds_amount: 1000 })).toBe(true);
  });
  it('never shows on opening balances', () => {
    expect(showTdsFields('opening_balance', true, { tds_amount: 5 })).toBe(false);
  });
});

describe('purchaseTdsSetting', () => {
  it('is only on with a TAN', () => {
    expect(purchaseTdsSetting(true, 'MUMA12345B')).toBe(true);
    expect(purchaseTdsSetting(true, '')).toBe(false);
    expect(purchaseTdsSetting(true, '   ')).toBe(false);
    expect(purchaseTdsSetting(true, null)).toBe(false);
    expect(purchaseTdsSetting(false, 'MUMA12345B')).toBe(false);
  });
});
