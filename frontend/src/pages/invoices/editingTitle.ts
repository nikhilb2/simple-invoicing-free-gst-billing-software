/**
 * The heading of the composer while an invoice is being edited (#935).
 *
 * It names the invoice by the number the user knows (INV-2026-009), as the
 * quotation heading already does. The database id is shown only while no
 * number is known, for example a purchase entry saved without one.
 */
export function editingInvoiceTitle(id: number, invoiceNumber: string | null | undefined): string {
  const number = invoiceNumber?.trim();
  return number ? `Editing ${number}` : `Editing invoice #${id}`;
}
