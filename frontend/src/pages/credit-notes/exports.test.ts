import { describe, expect, it, vi } from 'vitest';
import {
  buildCreditNotesCsv,
  CREDIT_NOTES_CSV_HEADERS,
  creditNoteToCsvRow,
  fetchAllPages,
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

describe('fetchAllPages', () => {
  it('calls the callback for pages 1..N and joins the items in order', async () => {
    const fetchPage = vi.fn(async (page: number) => ({
      items: [`page-${page}-a`, `page-${page}-b`],
      total_pages: 3,
    }));

    const items = await fetchAllPages<string>(fetchPage, 2);

    expect(items).toEqual([
      'page-1-a',
      'page-1-b',
      'page-2-a',
      'page-2-b',
      'page-3-a',
      'page-3-b',
    ]);
    expect(fetchPage.mock.calls).toEqual([
      [1, 2],
      [2, 2],
      [3, 2],
    ]);
  });

  it('stops at total_pages and does not fetch beyond it', async () => {
    const fetchPage = vi.fn(async () => ({ items: ['only'], total_pages: 1 }));

    expect(await fetchAllPages<string>(fetchPage, 500)).toEqual(['only']);
    expect(fetchPage).toHaveBeenCalledTimes(1);
  });

  it('stops on an empty page even when more pages are claimed', async () => {
    const fetchPage = vi.fn(async (page: number) => ({
      items: page === 1 ? ['first'] : [],
      total_pages: 5,
    }));

    expect(await fetchAllPages<string>(fetchPage, 500)).toEqual(['first']);
    expect(fetchPage).toHaveBeenCalledTimes(2);
  });
});

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
