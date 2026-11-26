import { describe, expect, it } from 'vitest';
import { invoiceToastMessage } from './invoiceToast';

const products = [
  { id: 1, maintain_inventory: true },
  { id: 2, maintain_inventory: true },
  { id: 3, maintain_inventory: false },
  { id: 4, maintain_inventory: false },
];
const line = (id: number) => ({ product_id: id });
const all = [line(1), line(2)];
const some = [line(1), line(3)];
const none = [line(3), line(4)];

describe('invoiceToastMessage', () => {
  it('sales: says nothing about stock when no line is tracked', () => {
    expect(invoiceToastMessage({ action: 'create', voucherType: 'sales', number: 'INV-2026-001', lines: none, products }))
      .toBe('Invoice INV-2026-001 saved.');
  });
  it('sales: all lines tracked', () => {
    expect(invoiceToastMessage({ action: 'create', voucherType: 'sales', number: 'INV-2026-001', lines: all, products }))
      .toBe('Invoice INV-2026-001 saved. Stock updated for 2 items.');
  });
  it('sales: some lines tracked', () => {
    expect(invoiceToastMessage({ action: 'create', voucherType: 'sales', number: 'INV-2026-001', lines: some, products }))
      .toBe('Invoice INV-2026-001 saved. Stock updated for 1 of 2 items.');
  });
  it('uses the singular for one item', () => {
    expect(invoiceToastMessage({ action: 'create', number: 'INV-1', lines: [line(1)], products }))
      .toBe('Invoice INV-1 saved. Stock updated for 1 item.');
  });
  it('purchase: added, with the same 1 of N rule, and none when untracked', () => {
    const base = { action: 'create' as const, voucherType: 'purchase' as const, number: 'PUR-1', products };
    expect(invoiceToastMessage({ ...base, lines: all })).toBe('Purchase invoice PUR-1 saved. Stock added for 2 items.');
    expect(invoiceToastMessage({ ...base, lines: some })).toBe('Purchase invoice PUR-1 saved. Stock added for 1 of 2 items.');
    expect(invoiceToastMessage({ ...base, lines: none })).toBe('Purchase invoice PUR-1 saved.');
  });
  it('edit: adjusted', () => {
    const base = { action: 'edit' as const, number: 'INV-1', products };
    expect(invoiceToastMessage({ ...base, lines: all })).toBe('Invoice INV-1 updated. Stock adjusted for 2 items.');
    expect(invoiceToastMessage({ ...base, lines: some })).toBe('Invoice INV-1 updated. Stock adjusted for 1 of 2 items.');
    expect(invoiceToastMessage({ ...base, lines: none })).toBe('Invoice INV-1 updated.');
  });
  it('from a quotation: then the sales stock sentence', () => {
    const base = { action: 'fromQuotation' as const, number: 'INV-1', sourceNumber: 'QUO-7', products };
    expect(invoiceToastMessage({ ...base, lines: all })).toBe('Invoice INV-1 created from QUO-7. Stock updated for 2 items.');
    expect(invoiceToastMessage({ ...base, lines: none })).toBe('Invoice INV-1 created from QUO-7.');
  });
  it('cancel: put back', () => {
    const base = { action: 'cancel' as const, number: 'INV-1', products };
    expect(invoiceToastMessage({ ...base, lines: all })).toBe('Invoice INV-1 cancelled. Stock put back for 2 items.');
    expect(invoiceToastMessage({ ...base, lines: some })).toBe('Invoice INV-1 cancelled. Stock put back for 1 of 2 items.');
    expect(invoiceToastMessage({ ...base, lines: none })).toBe('Invoice INV-1 cancelled.');
  });
  it('restore: taken out again', () => {
    const base = { action: 'restore' as const, number: 'INV-1', products };
    expect(invoiceToastMessage({ ...base, lines: all })).toBe('Invoice INV-1 restored. Stock taken out again for 2 items.');
    expect(invoiceToastMessage({ ...base, lines: some })).toBe('Invoice INV-1 restored. Stock taken out again for 1 of 2 items.');
    expect(invoiceToastMessage({ ...base, lines: none })).toBe('Invoice INV-1 restored.');
  });
  it('delivery challan: saved updated, edited adjusted', () => {
    expect(invoiceToastMessage({ action: 'challanCreate', number: 'DC-1', lines: some, products }))
      .toBe('Delivery challan DC-1 saved. Stock updated for 1 of 2 items.');
    expect(invoiceToastMessage({ action: 'challanEdit', number: 'DC-1', lines: all, products }))
      .toBe('Delivery challan DC-1 updated. Stock adjusted for 2 items.');
    expect(invoiceToastMessage({ action: 'challanCreate', number: 'DC-1', lines: none, products }))
      .toBe('Delivery challan DC-1 saved.');
  });
  it('falls back to the first sentence when lines or products are missing or unknown', () => {
    expect(invoiceToastMessage({ action: 'create', number: 'INV-1', lines: undefined, products })).toBe('Invoice INV-1 saved.');
    expect(invoiceToastMessage({ action: 'create', number: 'INV-1', lines: all, products: undefined })).toBe('Invoice INV-1 saved.');
    expect(invoiceToastMessage({ action: 'create', number: 'INV-1', lines: [], products })).toBe('Invoice INV-1 saved.');
    expect(invoiceToastMessage({ action: 'create', number: 'INV-1', lines: [line(1), line(99)], products })).toBe('Invoice INV-1 saved.');
  });
  it('copes with a missing number', () => {
    expect(invoiceToastMessage({ action: 'create', number: null, lines: none, products })).toBe('Invoice saved.');
  });
});
