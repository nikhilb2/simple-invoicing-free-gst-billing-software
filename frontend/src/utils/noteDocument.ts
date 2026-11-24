/**
 * How a credit/debit note is named when we view, download or share it.
 *
 * An outward note (against a sale) is our Credit Note. An inward note (a
 * purchase return or a supplier's discount) numbers out of our Debit Note
 * series and prints as our Debit Note, addressed to the supplier.
 */
export type NoteDocumentLabel = 'Credit Note' | 'Debit Note';

/** From a note's direction. Notes from before the column existed are outward. */
export function noteDocumentLabel(direction: string | null | undefined): NoteDocumentLabel {
  return direction === 'inward' ? 'Debit Note' : 'Credit Note';
}

/** From a ledger or day book row, which carries the label as its voucher type. */
export function noteDocumentLabelForVoucher(voucherType: string | null | undefined): NoteDocumentLabel {
  return voucherType === 'Debit Note' ? 'Debit Note' : 'Credit Note';
}

/** `credit_note_CN_26_0007.pdf` or `debit_note_DN-2026-001.pdf`, as the backend names it. */
export function noteDocumentFileName(label: NoteDocumentLabel, number: string | null | undefined, id: number): string {
  const prefix = label.toLowerCase().replace(' ', '_');
  return `${prefix}_${(number || String(id)).replace(/\//g, '_')}.pdf`;
}
