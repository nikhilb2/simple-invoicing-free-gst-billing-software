import { describe, expect, test } from 'vitest';
import { billedLineAmounts, invoiceDiscountAmount, returnPreviewTotal } from './creditNoteAmounts';

type Line = { id: number; quantity: number; taxable_amount: number; tax_amount: number; line_total: number };

function invoice(id: number, items: Line[], header: { total_amount: number; round_off_amount?: number; tcs_amount?: number; igst_amount?: number }) {
  const taxable = items.reduce((sum, item) => sum + item.taxable_amount, 0);
  const tax = items.reduce((sum, item) => sum + item.tax_amount, 0);
  return {
    id,
    taxable_amount: taxable,
    total_tax_amount: tax,
    round_off_amount: header.round_off_amount ?? 0,
    tcs_amount: header.tcs_amount ?? 0,
    igst_amount: header.igst_amount ?? 0,
    total_amount: header.total_amount,
    items,
  };
}

function fullReturn(inv: ReturnType<typeof invoice>) {
  return returnPreviewTotal(inv.items.map((item) => ({ invoice: inv, item, quantity: item.quantity })));
}

describe('billedLineAmounts', () => {
  test('a 10% invoice discount on 1,000 @ 18% bills 900 + 162, not the stored 1,180 (#797)', () => {
    const inv = invoice(1, [{ id: 11, quantity: 1, taxable_amount: 1000, tax_amount: 180, line_total: 1180 }], { total_amount: 1062 });

    expect(invoiceDiscountAmount(inv)).toBe(118);
    expect(billedLineAmounts(inv).get(11)).toEqual({ taxable: 900, tax: 162, lineTotal: 1062 });
  });

  test('an invoice with no discount or round-off keeps its stored figures', () => {
    const inv = invoice(1, [{ id: 11, quantity: 2, taxable_amount: 199.98, tax_amount: 36, line_total: 235.98 }], { total_amount: 235.98 });

    expect(billedLineAmounts(inv).get(11)).toEqual({ taxable: 199.98, tax: 36, lineTotal: 235.98 });
  });

  test('a row with only a total is used as is', () => {
    const inv = invoice(1, [{ id: 11, quantity: 1, taxable_amount: 0, tax_amount: 0, line_total: 500 }], { total_amount: 500 });

    expect(billedLineAmounts(inv).get(11)?.lineTotal).toBe(500);
  });

  test('lines of a discounted, rounded invoice add up to its total, as the server stores them', () => {
    // Two lines, 7.5% invoice discount, round-off on: the figures the server
    // writes for 3 x 333.33 @ 18% and 7 x 49.99 @ 12% (intrastate).
    // 999.99 + 179.99 + 349.93 + 41.99 = 1571.90; less 117.89 = 1454.01; rounds to 1454.
    const inv = invoice(1, [
      { id: 11, quantity: 3, taxable_amount: 999.99, tax_amount: 179.99, line_total: 1179.98 },
      { id: 12, quantity: 7, taxable_amount: 349.93, tax_amount: 41.99, line_total: 391.92 },
    ], { total_amount: 1454, round_off_amount: -0.01 });

    const lines = [...billedLineAmounts(inv).values()];
    const total = lines.reduce((sum, line) => sum + line.lineTotal, 0);
    expect(Math.round(total * 100) / 100).toBe(1454);
  });
});

describe('returnPreviewTotal', () => {
  test('a full return of a discounted invoice previews what was billed, not the undiscounted lines', () => {
    const inv = invoice(1, [{ id: 11, quantity: 1, taxable_amount: 1000, tax_amount: 180, line_total: 1180 }], { total_amount: 1062 });

    expect(fullReturn(inv)).toBe(1062);
  });

  test('half a discounted line previews half of what it billed', () => {
    const inv = invoice(1, [{ id: 11, quantity: 2, taxable_amount: 2000, tax_amount: 360, line_total: 2360 }], { total_amount: 2124 });

    expect(returnPreviewTotal([{ invoice: inv, item: inv.items[0], quantity: 1 }])).toBe(1062);
  });

  test('a full return of a discounted TCS invoice reverses all of its TCS', () => {
    // 100,000 + 18,000 GST, 18,000 off, 2% TCS on the 100,000 left.
    const inv = invoice(1, [{ id: 11, quantity: 1, taxable_amount: 100000, tax_amount: 18000, line_total: 118000 }], {
      total_amount: 102000, tcs_amount: 2000,
    });

    expect(fullReturn(inv)).toBe(102000);
  });

  test('a full return of a discounted, rounded multi-line invoice previews its whole total', () => {
    const inv = invoice(1, [
      { id: 11, quantity: 3, taxable_amount: 999.99, tax_amount: 179.99, line_total: 1179.98 },
      { id: 12, quantity: 7, taxable_amount: 349.93, tax_amount: 41.99, line_total: 391.92 },
    ], { total_amount: 1454, round_off_amount: -0.01 });

    expect(fullReturn(inv)).toBe(1454);
  });

  test('nothing selected previews zero', () => {
    const inv = invoice(1, [{ id: 11, quantity: 1, taxable_amount: 100, tax_amount: 18, line_total: 118 }], { total_amount: 118 });

    expect(returnPreviewTotal([{ invoice: inv, item: inv.items[0], quantity: 0 }])).toBe(0);
  });
});
