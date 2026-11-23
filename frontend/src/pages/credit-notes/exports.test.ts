import { describe, expect, it } from 'vitest';
import {
  buildCreditNotesCsv,
  CREDIT_NOTES_CSV_HEADERS,
  creditNoteToCsvRow,
} from './exports';
import type { CreditNote, Invoice, Ledger } from '../../types/api';
import { formatDate } from '../../utils/formatting';

const creditNote = (overrides: Partial<CreditNote> = {}): CreditNote => ({
  id: 1,
  credit_note_number: 'CN-1',
  ledger_id: 1,
  financial_year_id: null,
  credit_note_type: 'return',
  direction: 'outward',
  supplier_credit_note_number: null,
  supplier_credit_note_date: null,
  credit_note_date: '2026-11-10',
  reason: null,
  status: 'active',
  taxable_amount: 1000,
  cgst_amount: 90,
  sgst_amount: 90,
  igst_amount: 0,
  total_amount: 1180,
  created_at: '2026-11-10T10:00:00Z',
  cancelled_at: null,
  invoice_ids: [10],
  items: [],
  ...overrides,
});

const ledger = (overrides: Partial<Ledger> = {}): Ledger =>
  ({ id: 1, name: 'Acme Traders', ...overrides }) as Ledger;

const invoice = (overrides: Partial<Invoice> = {}): Invoice =>
  ({ id: 10, invoice_number: 'INV-1', ...overrides }) as Invoice;

describe('creditNoteToCsvRow', () => {
  it('maps a credit note to the header order', () => {
    expect(creditNoteToCsvRow(creditNote(), [ledger()], [invoice()])).toEqual([
      'CN-1',
      formatDate('2026-11-10'),
      'Acme Traders',
      'INV-1',
      1180,
    ]);
  });

  it('falls back to the ledger id when the ledger is not loaded', () => {
    expect(creditNoteToCsvRow(creditNote(), [], [])[2]).toBe('Ledger #1');
  });

  it('renders no original invoice when the note covers none', () => {
    expect(creditNoteToCsvRow(creditNote({ invoice_ids: [] }), [ledger()], [])[3]).toBe('');
  });
});

describe('buildCreditNotesCsv', () => {
  it('renders headers and rows', () => {
    expect(buildCreditNotesCsv([creditNote()], [ledger()], [invoice()])).toBe(
      `Number,Date,Ledger,Original invoice,Total\r\nCN-1,${formatDate('2026-11-10')},Acme Traders,INV-1,1180`,
    );
  });

  it('renders headers only for an empty list', () => {
    expect(buildCreditNotesCsv([], [], [])).toBe('Number,Date,Ledger,Original invoice,Total');
  });

  it('exposes the headers the page downloads', () => {
    expect(CREDIT_NOTES_CSV_HEADERS).toEqual([
      'Number',
      'Date',
      'Ledger',
      'Original invoice',
      'Total',
    ]);
  });
});
