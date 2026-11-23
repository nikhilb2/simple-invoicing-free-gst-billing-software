/**
 * Credit notes list CSV export.
 *
 * The credit notes list is paginated server side, so exporting only the rows
 * on screen would silently drop every note past the current page. This module
 * instead pages the list endpoint at its 500 row maximum with the same
 * filters the page applies, until the server's total_pages is reached, and
 * downloads every matching note. Quoting, the formula guard, and the UTF-8
 * BOM are owned by the shared helper in utils/csv.ts, so this module only
 * maps notes to rows and owns the paging.
 */
import { listCreditNotes } from '../../api/creditNotes';
import type { CreditNote, CreditNoteDirection, Invoice, Ledger } from '../../types/api';
import { creditNoteInvoiceLabels } from '../../utils/creditNoteInvoices';
import { toIsoDate } from '../../utils/dateRanges';
import { formatDate } from '../../utils/formatting';
import { downloadCsv, toCsv, type CsvValue } from '../../utils/csv';
import { fetchAllPages } from '../../utils/pagination';

/** Columns of the export, in order. */
export const CREDIT_NOTES_CSV_HEADERS = ['Number', 'Date', 'Ledger', 'Original invoice', 'Total'];

/** The list filters the export carries over from the page, in order. */
export type CreditNoteExportFilters = {
  search?: string;
  status?: string;
  direction?: CreditNoteDirection;
  date_from?: string;
  date_to?: string;
};

/**
 * Every credit note the current filters select, across all pages.
 */
export async function fetchAllCreditNotes(filters: CreditNoteExportFilters): Promise<CreditNote[]> {
  return fetchAllPages<CreditNote>(async (page, pageSize) => {
    const res = await listCreditNotes({ ...filters, page, page_size: pageSize });
    return { items: res.data.items, total_pages: res.data.total_pages };
  });
}

/**
 * One credit note as a CSV row, in header order. The ledger name and the
 * original invoice numbers come from the lists the page already loaded.
 */
export function creditNoteToCsvRow(
  creditNote: CreditNote,
  ledgers: Ledger[],
  invoices: Invoice[],
): CsvValue[] {
  const ledger = ledgers.find((entry) => entry.id === creditNote.ledger_id);
  return [
    creditNote.credit_note_number,
    formatDate(creditNote.credit_note_date ?? creditNote.created_at),
    ledger?.name || `Ledger #${creditNote.ledger_id}`,
    creditNoteInvoiceLabels(creditNote.invoice_ids, invoices),
    creditNote.total_amount,
  ];
}

/** CSV text for a set of credit notes, headers included. */
export function buildCreditNotesCsv(
  creditNotes: CreditNote[],
  ledgers: Ledger[],
  invoices: Invoice[],
): string {
  return toCsv(
    CREDIT_NOTES_CSV_HEADERS,
    creditNotes.map((creditNote) => creditNoteToCsvRow(creditNote, ledgers, invoices)),
  );
}

/** Fetches every matching credit note and downloads it as a CSV file. */
export async function exportCreditNotesCsv(
  filters: CreditNoteExportFilters,
  ledgers: Ledger[],
  invoices: Invoice[],
): Promise<void> {
  const creditNotes = await fetchAllCreditNotes(filters);
  downloadCsv(
    `credit_notes_${toIsoDate(new Date())}.csv`,
    CREDIT_NOTES_CSV_HEADERS,
    creditNotes.map((creditNote) => creditNoteToCsvRow(creditNote, ledgers, invoices)),
  );
}
