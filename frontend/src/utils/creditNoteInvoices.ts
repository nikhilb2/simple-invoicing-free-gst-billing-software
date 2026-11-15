import type { Invoice } from '../types/api';

/**
 * The invoices a credit note was raised against, as invoice numbers.
 * An id that is not in the loaded invoices (cancelled ones are left out)
 * or has no number is shown as `#<id>`.
 */
export function creditNoteInvoiceLabels(
  invoiceIds: number[],
  invoices: Pick<Invoice, 'id' | 'invoice_number'>[],
): string {
  const numbers = new Map(invoices.map((invoice) => [invoice.id, invoice.invoice_number]));
  return invoiceIds.map((id) => numbers.get(id) || `#${id}`).join(', ');
}
