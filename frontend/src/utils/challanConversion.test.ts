import { describe, expect, it } from 'vitest';
import { challanQuantityNotes, challanReferenceText, formatNoteQuantity, readChallanAlreadyInvoiced } from './challanConversion';

const products = [
  { id: 1, name: 'Widget', maintain_inventory: true },
  { id: 2, name: 'Service pack', maintain_inventory: false },
  { id: 3, name: 'Gadget', maintain_inventory: true },
];

describe('formatNoteQuantity', () => {
  it('drops trailing zeros and keeps up to three decimals', () => {
    expect(formatNoteQuantity(20)).toBe('20');
    expect(formatNoteQuantity(2.5)).toBe('2.5');
    expect(formatNoteQuantity(0.125)).toBe('0.125');
    expect(formatNoteQuantity(1.23456)).toBe('1.235');
    expect(formatNoteQuantity(0.1 + 0.2)).toBe('0.3');
    expect(formatNoteQuantity(0)).toBe('0');
  });
});

describe('challanQuantityNotes', () => {
  it('says nothing when quantities match', () => {
    expect(challanQuantityNotes(
      [{ product_id: 1, product_name: 'Widget', quantity: 10 }],
      [{ productId: 1, quantity: 10 }],
      products,
    )).toEqual([]);
  });

  it('notes goods added back when the invoice has fewer', () => {
    const [note] = challanQuantityNotes(
      [{ product_id: 1, product_name: 'Widget', quantity: 10 }],
      [{ productId: 1, quantity: 7.5 }],
      products,
    );
    expect(note.direction).toBe('back_to_stock');
    expect(note.difference).toBe(2.5);
    expect(note.message).toBe("Widget: challan 10, invoicing 7.5. 2.5 will be added back to stock. Make sure they're returned.");
  });

  it('notes extra reduction when the invoice has more', () => {
    const [note] = challanQuantityNotes(
      [{ product_id: 1, product_name: 'Widget', quantity: 10 }],
      [{ productId: 1, quantity: 12 }],
      products,
    );
    expect(note.direction).toBe('more_out');
    expect(note.message).toBe('Widget: challan 10, invoicing 12. 2 more will be reduced from stock.');
  });

  it('ignores floating-point noise when the same product is on several lines', () => {
    expect(challanQuantityNotes(
      [{ product_id: 1, product_name: 'Widget', quantity: 0.1 }, { product_id: 1, product_name: 'Widget', quantity: 0.2 }],
      [{ productId: 1, quantity: 0.3 }],
      products,
    )).toEqual([]);
    expect(challanQuantityNotes(
      [{ product_id: 1, product_name: 'Widget', quantity: 0.3 }],
      [{ productId: 1, quantity: 0.1 }, { productId: 1, quantity: 0.2 }],
      products,
    )).toEqual([]);
  });

  it('sums lines per product on both sides', () => {
    const [note] = challanQuantityNotes(
      [{ product_id: 1, product_name: 'Widget', quantity: 4 }, { product_id: 1, product_name: 'Widget', quantity: 6 }],
      [{ productId: 1, quantity: 3 }, { productId: 1, quantity: 4 }],
      products,
    );
    expect(note.challanQuantity).toBe(10);
    expect(note.invoiceQuantity).toBe(7);
    expect(note.difference).toBe(3);
  });

  it('counts a removed line as zero invoiced and NaN as zero', () => {
    const notes = challanQuantityNotes(
      [{ product_id: 1, product_name: 'Widget', quantity: 5 }, { product_id: 3, product_name: 'Gadget', quantity: 2 }],
      [{ productId: 3, quantity: Number.NaN }],
      products,
    );
    expect(notes.map((n) => n.invoiceQuantity)).toEqual([0, 0]);
    expect(notes[0].message).toContain('Widget: challan 5, invoicing 0. 5 will be added back');
  });

  it('ignores products that are not on the challan', () => {
    expect(challanQuantityNotes(
      [{ product_id: 1, product_name: 'Widget', quantity: 5 }],
      [{ productId: 1, quantity: 5 }, { productId: 3, quantity: 9 }],
      products,
    )).toEqual([]);
  });

  it('skips products that do not maintain inventory', () => {
    expect(challanQuantityNotes(
      [{ product_id: 2, product_name: 'Service pack', quantity: 5 }],
      [{ productId: 2, quantity: 1 }],
      products,
    )).toEqual([]);
  });

  it('treats an unknown product as tracked and falls back to the challan name, then the id', () => {
    const notes = challanQuantityNotes(
      [{ product_id: 8, product_name: 'Old item', quantity: 5 }, { product_id: 9, product_name: null, quantity: 5 }],
      [{ productId: 8, quantity: 4 }, { productId: 9, quantity: 4 }],
      products,
    );
    expect(notes[0].message.startsWith('Old item:')).toBe(true);
    expect(notes[1].message.startsWith('Product 9:')).toBe(true);
  });

  it('prefers the product list name and keeps the challan order', () => {
    const notes = challanQuantityNotes(
      [{ product_id: 3, product_name: 'stale', quantity: 1 }, { product_id: 1, product_name: 'stale', quantity: 1 }],
      [{ productId: 3, quantity: 2 }, { productId: 1, quantity: 2 }],
      products,
    );
    expect(notes.map((n) => n.productId)).toEqual([3, 1]);
    expect(notes[0].message.startsWith('Gadget:')).toBe(true);
  });
});

describe('readChallanAlreadyInvoiced', () => {
  const apiError = (status: number, detail: unknown) => ({
    isAxiosError: true,
    message: `Request failed with status code ${status}`,
    response: { status, data: { detail } },
  });

  it('reads the message and invoice number of an already-invoiced refusal', () => {
    const err = apiError(409, {
      code: 'challan_already_invoiced',
      message: 'DC-2026-019 was already invoiced as INV-2026-149',
      invoice_id: 7,
      invoice_number: 'INV-2026-149',
    });
    expect(readChallanAlreadyInvoiced(err)).toEqual({
      message: 'DC-2026-019 was already invoiced as INV-2026-149',
      invoiceNumber: 'INV-2026-149',
    });
  });

  it('has no invoice number when the server sends none', () => {
    const err = apiError(409, { code: 'challan_already_invoiced', message: 'DC-1 was already invoiced', invoice_number: null });
    expect(readChallanAlreadyInvoiced(err)).toEqual({ message: 'DC-1 was already invoiced', invoiceNumber: null });
  });

  it('ignores other refusals and plain errors', () => {
    expect(readChallanAlreadyInvoiced(apiError(409, { code: 'challan_cancelled', message: 'DC-1 is cancelled' }))).toBeNull();
    expect(readChallanAlreadyInvoiced(apiError(404, 'Delivery challan not found'))).toBeNull();
    expect(readChallanAlreadyInvoiced(new Error('Network Error'))).toBeNull();
  });
});

describe('challanReferenceText', () => {
  it('names the challan with its date, as the invoice PDF does', () => {
    expect(challanReferenceText('DC-2026-004', '2026-11-16')).toBe('DC-2026-004 dated 16-11-2026');
  });

  it('falls back to the number alone without a date', () => {
    expect(challanReferenceText('DC-2026-004', null)).toBe('DC-2026-004');
    expect(challanReferenceText('DC-2026-004', undefined)).toBe('DC-2026-004');
  });
});
