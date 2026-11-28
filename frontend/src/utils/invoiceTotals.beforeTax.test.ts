import { describe, expect, it } from 'vitest';
import { billDiscountAmount, computeInvoiceTotals, gstHeads, shareByWeight } from './invoiceTotals';

/* #1154: the bill discount comes off the subtotal before GST. Each figure here is the
   one the server saves for the same bill (backend tests/services/test_bill_discount_before_gst.py). */

const hamper = { unitPrice: 300, quantity: 1, gstRate: 18 };
const intraState = { taxInclusive: false, interstateSupply: false, discountMode: 'before_tax' as const };

describe('a bill discount before GST', () => {
  it('one line, flat: ₹50 off ₹300 @ 18% is ₹295.00', () => {
    const result = computeInvoiceTotals([hamper], { ...intraState, invoiceDiscount: { type: 'net', value: 50 } });
    expect(result).toEqual({
      subtotal: 300, billDiscountAmount: 50, billDiscountShares: [50], billDiscountTooLarge: false,
      taxableAmount: 250, taxAmount: 45, totalAmount: 295,
      invoiceDiscountAmount: 0, afterDiscountTotal: 295, roundOffAmount: 0, total: 295,
    });
    expect(gstHeads(result.taxAmount, false)).toEqual({ cgstAmount: 22.5, sgstAmount: 22.5, igstAmount: 0 });
  });

  it('one line, 10% with round off: taxable 270, GST 24.30 + 24.30, total rounded half-up to ₹319', () => {
    const result = computeInvoiceTotals([hamper], {
      ...intraState, invoiceDiscount: { type: 'percentage', value: 10 }, applyRoundOff: true,
    });
    expect(result.billDiscountAmount).toBe(30);
    expect(result.taxableAmount).toBe(270);
    expect(gstHeads(result.taxAmount, false)).toEqual({ cgstAmount: 24.3, sgstAmount: 24.3, igstAmount: 0 });
    // 318.60 rounds to 319.00 as every round off does today (the spec's example says 318.00).
    expect(result.afterDiscountTotal).toBe(318.6);
    expect(result.roundOffAmount).toBe(0.4);
    expect(result.total).toBe(319);
  });

  it('mixed rates: shares 33.33 / 16.67, GST per line, ₹273.34 and ₹273 with round off', () => {
    const lines = [{ unitPrice: 200, quantity: 1, gstRate: 5 }, { unitPrice: 100, quantity: 1, gstRate: 18 }];
    const result = computeInvoiceTotals(lines, { ...intraState, invoiceDiscount: { type: 'net', value: 50 } });
    expect(result.billDiscountShares).toEqual([33.33, 16.67]);
    expect(result.taxableAmount).toBe(250);
    expect(gstHeads(result.taxAmount, false)).toEqual({ cgstAmount: 11.67, sgstAmount: 11.67, igstAmount: 0 });
    expect(result.total).toBe(273.34);

    const rounded = computeInvoiceTotals(lines, {
      ...intraState, invoiceDiscount: { type: 'net', value: 50 }, applyRoundOff: true,
    });
    expect(rounded.roundOffAmount).toBe(-0.34);
    expect(rounded.total).toBe(273);

    // The same bill after GST, as documents saved before #1154 keep it.
    const old = computeInvoiceTotals(lines, {
      ...intraState, discountMode: 'after_tax', invoiceDiscount: { type: 'net', value: 50 }, applyRoundOff: true,
    });
    expect(old.total).toBe(278);
    expect(old).not.toHaveProperty('subtotal');
  });

  it('remainder paisa: ₹100 over three equal lines is 33.34, 33.33, 33.33', () => {
    const line = { unitPrice: 100, quantity: 1, gstRate: 18 };
    const result = computeInvoiceTotals([line, line, line], { ...intraState, invoiceDiscount: { type: 'net', value: 100 } });
    expect(result.billDiscountShares).toEqual([33.34, 33.33, 33.33]);
    expect(result.taxableAmount).toBe(200);
  });

  it('inter-state: IGST ₹45.00, total ₹295.00', () => {
    const result = computeInvoiceTotals([hamper], {
      ...intraState, interstateSupply: true, invoiceDiscount: { type: 'net', value: 50 },
    });
    expect(gstHeads(result.taxAmount, true)).toEqual({ cgstAmount: 0, sgstAmount: 0, igstAmount: 45 });
    expect(result.total).toBe(295);
  });

  it('line discount then bill discount: subtotal 270, taxable 220, GST 39.60, total 259.60', () => {
    const result = computeInvoiceTotals([{ ...hamper, discountType: 'percentage', discountValue: 10 }], {
      ...intraState, invoiceDiscount: { type: 'net', value: 50 },
    });
    expect(result.subtotal).toBe(270);
    expect(result.taxableAmount).toBe(220);
    expect(result.taxAmount).toBe(39.6);
    expect(result.total).toBe(259.6);
  });

  it('no discount gives the same figures as today, with no Subtotal to show', () => {
    const result = computeInvoiceTotals([hamper], intraState);
    expect(result).toMatchObject({ subtotal: 300, billDiscountAmount: 0, taxableAmount: 300, taxAmount: 54, total: 354 });
    const today = computeInvoiceTotals([hamper], { ...intraState, discountMode: 'after_tax' });
    expect(result.total).toBe(today.total);
  });

  it('price already includes GST: ₹354 inclusive less ₹50 off the ex-GST ₹300 is ₹295.00', () => {
    const result = computeInvoiceTotals([{ unitPrice: 354, quantity: 1, gstRate: 18 }], {
      ...intraState, taxInclusive: true, invoiceDiscount: { type: 'net', value: 50 },
    });
    expect(result).toMatchObject({ subtotal: 300, taxableAmount: 250, taxAmount: 45, total: 295 });
  });

  it('inclusive 999 @ 18% intra-state: 10% off 846.62 is 84.66, CGST = SGST = 68.58, total 899.12', () => {
    const result = computeInvoiceTotals([{ unitPrice: 999, quantity: 1, gstRate: 18 }], {
      ...intraState, taxInclusive: true, invoiceDiscount: { type: 'percentage', value: 10 },
    });
    expect(result.subtotal).toBe(846.62);
    expect(result.billDiscountShares).toEqual([84.66]);
    expect(result.taxableAmount).toBe(761.96);
    expect(gstHeads(result.taxAmount, false)).toEqual({ cgstAmount: 68.58, sgstAmount: 68.58, igstAmount: 0 });
    expect(result.total).toBe(899.12);
  });

  it('a discount equal to the subtotal is allowed and totals ₹0.00', () => {
    const flat = computeInvoiceTotals([hamper], { ...intraState, invoiceDiscount: { type: 'net', value: 300 } });
    expect(flat).toMatchObject({ billDiscountTooLarge: false, taxableAmount: 0, taxAmount: 0, total: 0 });
    const full = computeInvoiceTotals([hamper], { ...intraState, invoiceDiscount: { type: 'percentage', value: 100 } });
    expect(full).toMatchObject({ billDiscountTooLarge: false, total: 0 });
  });

  it('a discount over the subtotal is flagged and left out, so nothing goes negative', () => {
    const flat = computeInvoiceTotals([hamper], { ...intraState, invoiceDiscount: { type: 'net', value: 350 } });
    expect(flat).toMatchObject({ billDiscountTooLarge: true, billDiscountAmount: 0, taxableAmount: 300, total: 354 });
    const percent = computeInvoiceTotals([hamper], { ...intraState, invoiceDiscount: { type: 'percentage', value: 101 } });
    expect(percent).toMatchObject({ billDiscountTooLarge: true, total: 354 });
  });

  it('TCS is worked out on the total after the discount', () => {
    const result = computeInvoiceTotals([{ unitPrice: 100000, quantity: 1, gstRate: 18 }], {
      ...intraState, interstateSupply: true, invoiceDiscount: { type: 'net', value: 18000 }, tcs: { rate: 2 },
    });
    // backend test_tcs_invoices: 82000 + 14760 = 96760, TCS 1935.20.
    expect(result).toMatchObject({ taxableAmount: 82000, taxAmount: 14760, tcsBaseAmount: 96760, tcsAmount: 1935.2, total: 98695.2 });
  });
});

describe('paise arithmetic for the share', () => {
  it('rounds the % half-up exactly, where binary floats fall a hair short', () => {
    // 1.25 x 1.5% = 0.01875 -> 0.02; 0.125 x 3 as floats is 0.37499...
    expect(billDiscountAmount(1.25, { type: 'percentage', value: 1.5 })).toBe(0.02);
    expect(billDiscountAmount(0.15, { type: 'percentage', value: 50 })).toBe(0.08);
    expect(billDiscountAmount(300, { type: 'net', value: 0.005 })).toBe(0.01);
    expect(billDiscountAmount(300, { type: 'net', value: -5 })).toBe(0);
  });

  it('splits like _split_by_weight: the residue on the largest line, the first on a tie', () => {
    expect(shareByWeight(0.01, [100, 200, 200])).toEqual([0, 0.01, 0]);
    expect(shareByWeight(50, [200, 100])).toEqual([33.33, 16.67]);
    expect(shareByWeight(10, [0, 0])).toEqual([0, 0]);
    const shares = shareByWeight(99.99, [33.33, 33.33, 33.34]);
    expect(Math.round(shares.reduce((sum, share) => sum + share, 0) * 100)).toBe(9999);
  });
});
