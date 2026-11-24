import type { LedgerEntryCounts } from '../types/api';
import { plural } from './formatting';

/** "a", "a and b", "a, b and c". */
function joinList(parts: string[]): string {
  if (parts.length <= 1) return parts.join('');
  return `${parts.slice(0, -1).join(', ')} and ${parts[parts.length - 1]}`;
}

/** The documents deleting the ledger cancels, in words, e.g. "6 invoices, 3 receipts and 1 credit note". */
export function cancelledDocumentsPhrase(counts: LedgerEntryCounts): string {
  const invoices = counts.sales_invoices + counts.purchase_invoices;
  const parts: string[] = [];
  if (invoices) parts.push(plural(invoices, 'invoice'));
  if (counts.receipts) parts.push(plural(counts.receipts, 'receipt'));
  if (counts.payments) parts.push(plural(counts.payments, 'payment'));
  if (counts.credit_notes) parts.push(plural(counts.credit_notes, 'credit note'));
  if (counts.delivery_challans) parts.push(plural(counts.delivery_challans, 'delivery challan'));
  if (counts.quotations) parts.push(plural(counts.quotations, 'quotation'));
  if (counts.opening_balance) parts.push('the opening balance');
  return joinList(parts);
}

/** Shown, as a warning of its own, when an invoice to cancel is from an earlier month. */
export const FILED_GSTR1_WARNING = 'Invoices from past months may already be in a GSTR-1 you filed.';

/** The warning's lines, in order: what is cancelled first, "can't undo" last. */
export function ledgerDeletionWarnings(counts: LedgerEntryCounts): string[] {
  const documents = cancelledDocumentsPhrase(counts);
  if (!documents) {
    return [
      'Everything on this ledger is already cancelled. Deleting it hides the ledger from your lists.',
      'The cancelled entries stay in your records and reports as cancelled.',
      "You can't undo this.",
    ];
  }
  const lines = [`This cancels ${documents} for this party.`];
  if (counts.sales_invoices + counts.purchase_invoices > 0) {
    lines.push('Stock on these invoices goes back.');
  }
  lines.push('The cancelled entries stay in your records and reports as cancelled.');
  if (counts.share_links > 0) {
    lines.push(`${plural(counts.share_links, 'public link')} to this party's statement or bills will stop working.`);
  }
  lines.push("You can't undo this.");
  return lines;
}

/** The typed confirmation matches the ledger's name, ignoring case and outer spaces. */
export function ledgerNameConfirmed(typed: string, ledgerName: string): boolean {
  const wanted = ledgerName.trim().toLocaleLowerCase();
  return wanted.length > 0 && typed.trim().toLocaleLowerCase() === wanted;
}

/** The success toast after deleting a ledger with its entries. */
export function ledgerDeletedMessage(ledgerName: string, cancelled: LedgerEntryCounts): string {
  const documents = cancelledDocumentsPhrase(cancelled);
  return documents
    ? `${ledgerName} deleted. Cancelled ${documents}.`
    : `${ledgerName} deleted.`;
}
