import { describe, expect, test } from 'vitest';
import {
  noteDocumentFileName,
  noteDocumentLabel,
  noteDocumentLabelForVoucher,
} from './noteDocument';

describe('noteDocumentLabel', () => {
  test('an inward note is a Debit Note', () => {
    expect(noteDocumentLabel('inward')).toBe('Debit Note');
  });

  test('an outward note, or one with no direction, is a Credit Note', () => {
    expect(noteDocumentLabel('outward')).toBe('Credit Note');
    expect(noteDocumentLabel(null)).toBe('Credit Note');
    expect(noteDocumentLabel(undefined)).toBe('Credit Note');
  });
});

describe('noteDocumentLabelForVoucher', () => {
  test('a ledger row follows its voucher type', () => {
    expect(noteDocumentLabelForVoucher('Debit Note')).toBe('Debit Note');
    expect(noteDocumentLabelForVoucher('Credit Note')).toBe('Credit Note');
    expect(noteDocumentLabelForVoucher(null)).toBe('Credit Note');
  });
});

describe('noteDocumentFileName', () => {
  test('names the file after the document and its number', () => {
    expect(noteDocumentFileName('Debit Note', 'DN-2026-001', 7)).toBe('debit_note_DN-2026-001.pdf');
    expect(noteDocumentFileName('Credit Note', 'CN/26/0007', 7)).toBe('credit_note_CN_26_0007.pdf');
  });

  test('falls back to the id when the number is missing', () => {
    expect(noteDocumentFileName('Debit Note', null, 42)).toBe('debit_note_42.pdf');
  });
});
