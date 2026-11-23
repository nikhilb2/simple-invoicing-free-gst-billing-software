import { describe, expect, it } from 'vitest';
import { editingInvoiceTitle } from './editingTitle';

describe('editingInvoiceTitle', () => {
  it('names the invoice by its number, not its database id', () => {
    expect(editingInvoiceTitle(23, 'INV-2026-009')).toBe('Editing INV-2026-009');
  });

  it('falls back to the id while no number is known', () => {
    expect(editingInvoiceTitle(23, null)).toBe('Editing invoice #23');
    expect(editingInvoiceTitle(23, undefined)).toBe('Editing invoice #23');
    expect(editingInvoiceTitle(23, '  ')).toBe('Editing invoice #23');
  });
});
