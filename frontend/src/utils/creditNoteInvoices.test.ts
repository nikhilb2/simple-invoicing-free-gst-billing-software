import { describe, expect, test } from 'vitest';
import { creditNoteInvoiceLabels } from './creditNoteInvoices';

const invoices = [
  { id: 41, invoice_number: 'INV-2026-27-0003' },
  { id: 57, invoice_number: 'INV-2026-27-0009' },
  { id: 60, invoice_number: null },
];

describe('creditNoteInvoiceLabels', () => {
  test('known ids are shown as invoice numbers', () => {
    expect(creditNoteInvoiceLabels([41, 57], invoices)).toBe('INV-2026-27-0003, INV-2026-27-0009');
  });

  test('an id that is not loaded or has no number falls back to #id', () => {
    expect(creditNoteInvoiceLabels([41, 99, 60], invoices)).toBe('INV-2026-27-0003, #99, #60');
  });

  test('no invoices gives an empty string', () => {
    expect(creditNoteInvoiceLabels([], invoices)).toBe('');
  });
});
