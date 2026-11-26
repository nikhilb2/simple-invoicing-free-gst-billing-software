import { describe, expect, it } from 'vitest';
import { invoiceCancelConfirmMessage, invoiceToastMessage } from './invoiceToast';

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
    const base = { action: 'edit' as const, voucherType: 'sales' as const, number: 'INV-1', products };
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
    const base = { action: 'cancel' as const, voucherType: 'sales' as const, number: 'INV-1', products };
    expect(invoiceToastMessage({ ...base, lines: all })).toBe('Invoice INV-1 cancelled. Stock put back for 2 items.');
    expect(invoiceToastMessage({ ...base, lines: some })).toBe('Invoice INV-1 cancelled. Stock put back for 1 of 2 items.');
    expect(invoiceToastMessage({ ...base, lines: none })).toBe('Invoice INV-1 cancelled.');
  });
  it('restore: taken out again', () => {
    const base = { action: 'restore' as const, voucherType: 'sales' as const, number: 'INV-1', products };
    expect(invoiceToastMessage({ ...base, lines: all })).toBe('Invoice INV-1 restored. Stock taken out again for 2 items.');
    expect(invoiceToastMessage({ ...base, lines: some })).toBe('Invoice INV-1 restored. Stock taken out again for 1 of 2 items.');
    expect(invoiceToastMessage({ ...base, lines: none })).toBe('Invoice INV-1 restored.');
  });
  it('purchase, edit: adjusted, with the purchase label', () => {
    const base = { action: 'edit' as const, voucherType: 'purchase' as const, number: 'PUR-1', products };
    expect(invoiceToastMessage({ ...base, lines: all })).toBe('Purchase invoice PUR-1 updated. Stock adjusted for 2 items.');
    expect(invoiceToastMessage({ ...base, lines: some })).toBe('Purchase invoice PUR-1 updated. Stock adjusted for 1 of 2 items.');
    expect(invoiceToastMessage({ ...base, lines: none })).toBe('Purchase invoice PUR-1 updated.');
  });
  it('purchase, cancel: taken out', () => {
    const base = { action: 'cancel' as const, voucherType: 'purchase' as const, number: 'PUR-1', products };
    expect(invoiceToastMessage({ ...base, lines: all })).toBe('Purchase invoice PUR-1 cancelled. Stock taken out for 2 items.');
    expect(invoiceToastMessage({ ...base, lines: [line(1)] })).toBe('Purchase invoice PUR-1 cancelled. Stock taken out for 1 item.');
    expect(invoiceToastMessage({ ...base, lines: some })).toBe('Purchase invoice PUR-1 cancelled. Stock taken out for 1 of 2 items.');
    expect(invoiceToastMessage({ ...base, lines: none })).toBe('Purchase invoice PUR-1 cancelled.');
  });
  it('purchase, restore: added back', () => {
    const base = { action: 'restore' as const, voucherType: 'purchase' as const, number: 'PUR-1', products };
    expect(invoiceToastMessage({ ...base, lines: all })).toBe('Purchase invoice PUR-1 restored. Stock added back for 2 items.');
    expect(invoiceToastMessage({ ...base, lines: some })).toBe('Purchase invoice PUR-1 restored. Stock added back for 1 of 2 items.');
    expect(invoiceToastMessage({ ...base, lines: none })).toBe('Purchase invoice PUR-1 restored.');
  });
  it('edit, cancel and restore without a voucher type: only the first sentence', () => {
    expect(invoiceToastMessage({ action: 'edit', number: 'PUR-1', lines: all, products })).toBe('Invoice PUR-1 updated.');
    expect(invoiceToastMessage({ action: 'cancel', number: 'PUR-1', lines: all, products })).toBe('Invoice PUR-1 cancelled.');
    expect(invoiceToastMessage({ action: 'restore', number: 'PUR-1', lines: all, products })).toBe('Invoice PUR-1 restored.');
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

describe('invoiceCancelConfirmMessage', () => {
  it('sales: says stock will be put back only for tracked lines', () => {
    const base = { number: 'INV-1', voucherType: 'sales' as const, products };
    expect(invoiceCancelConfirmMessage({ ...base, lines: all }))
      .toBe('Cancel invoice INV-1? Stock will be put back for 2 items. You can still see it when you show cancelled invoices.');
    expect(invoiceCancelConfirmMessage({ ...base, lines: some }))
      .toBe('Cancel invoice INV-1? Stock will be put back for 1 of 2 items. You can still see it when you show cancelled invoices.');
    expect(invoiceCancelConfirmMessage({ ...base, lines: none }))
      .toBe('Cancel invoice INV-1? You can still see it when you show cancelled invoices.');
  });
  it('purchase: taken out', () => {
    expect(invoiceCancelConfirmMessage({ number: 'PUR-1', voucherType: 'purchase', lines: [line(1)], products }))
      .toBe('Cancel invoice PUR-1? Stock will be taken out for 1 item. You can still see it when you show cancelled invoices.');
  });
  it('no stock sentence when the voucher type, lines or products are unknown', () => {
    const tail = 'You can still see it when you show cancelled invoices.';
    expect(invoiceCancelConfirmMessage({ number: 'INV-1', voucherType: null, lines: all, products })).toBe(`Cancel invoice INV-1? ${tail}`);
    expect(invoiceCancelConfirmMessage({ number: 'INV-1', voucherType: 'sales', lines: null, products })).toBe(`Cancel invoice INV-1? ${tail}`);
    expect(invoiceCancelConfirmMessage({ number: null, voucherType: 'sales', lines: all, products: null })).toBe(`Cancel this invoice? ${tail}`);
  });
});
