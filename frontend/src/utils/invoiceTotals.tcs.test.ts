import { describe, expect, it } from 'vitest';
import { computeInvoiceTotals } from './invoiceTotals';

const scrap = [{ unitPrice: 100000, quantity: 1, gstRate: 18 }];

describe('TCS in invoice previews (#769), matching the server to the paisa', () => {
  it('scrap example: 1,00,000 + 18% GST collects 2,360 TCS for a total of 1,20,360', () => {
    const result = computeInvoiceTotals(scrap, {
      taxInclusive: false, interstateSupply: false, tcs: { rate: 2, base: 'gross' },
    });
    expect(result.taxableAmount).toBe(100000);
    expect(result.taxAmount).toBe(18000);
    expect(result.tcsBaseAmount).toBe(118000);
    expect(result.tcsAmount).toBe(2360);
    expect(result.total).toBe(120360);
  });

  it('applies the round-off after TCS (same case as test_round_off_is_applied_after_tcs)', () => {
    const result = computeInvoiceTotals([{ unitPrice: 1234.56, quantity: 1, gstRate: 18 }], {
      taxInclusive: false, interstateSupply: false, applyRoundOff: true, tcs: { rate: 2 },
    });
    expect(result.afterDiscountTotal).toBe(1456.78);
    expect(result.tcsAmount).toBe(29.14);
    expect(result.roundOffAmount).toBe(0.08);
    expect(result.total).toBe(1486);
  });

  it('works TCS out on the amount after the invoice discount', () => {
    const result = computeInvoiceTotals(scrap, {
      taxInclusive: false, invoiceDiscount: { type: 'net', value: 18000 }, tcs: { rate: 2 },
    });
    expect(result.tcsBaseAmount).toBe(100000);
    expect(result.tcsAmount).toBe(2000);
    expect(result.total).toBe(102000);
  });

  it('takes the pre-GST share for a section whose base is taxable', () => {
    const result = computeInvoiceTotals(scrap, { taxInclusive: false, tcs: { rate: 2, base: 'taxable' } });
    expect(result.tcsBaseAmount).toBe(100000);
    expect(result.tcsAmount).toBe(2000);
  });

  it('uses a typed amount over base x rate', () => {
    const result = computeInvoiceTotals(scrap, { taxInclusive: false, tcs: { rate: 2, amount: 2000 } });
    expect(result.tcsAmount).toBe(2000);
    expect(result.total).toBe(120000);
  });

  it('uses the no-PAN 5% rate the same way', () => {
    expect(computeInvoiceTotals(scrap, { taxInclusive: false, tcs: { rate: 5 } }).total).toBe(123900);
  });

  it('leaves the totals and their shape unchanged with no TCS', () => {
    const without = computeInvoiceTotals(scrap, { taxInclusive: false, applyRoundOff: true });
    expect(without).toEqual(computeInvoiceTotals(scrap, { taxInclusive: false, applyRoundOff: true, tcs: null }));
    expect('tcsAmount' in without).toBe(false);
    expect(without.total).toBe(118000);
  });
});
