import formatCurrency from '../../utils/formatting';

/** The texts of the composer's totals block (#1154), in components/ComposerTotals.tsx. */

/** The bill discount's amount box. */
export const BILL_DISCOUNT_ID = 'invoice-bill-discount';

/** A signed amount with a real minus, as the totals block shows it: "−₹50.00". */
export function signedCurrency(value: number, currencyCode: string): string {
  const rounded = Math.round(value * 100) / 100;
  return `${rounded < 0 ? '−' : ''}${formatCurrency(Math.abs(rounded), currencyCode)}`;
}

/** The hint under Total while a before-GST discount is on (#1154). */
export function billDiscountHint(gstRates: number[]): string {
  return new Set(gstRates).size > 1
    ? 'GST is charged on the amount after the discount, shared across the items by their value.'
    : 'GST is charged on the amount after the discount.';
}

/** The note on a document saved before #1154 with its discount after GST, opened for editing. */
export function oldDocumentNote(noun: 'invoice' | 'quotation', switched: boolean, totals?: { from: string; to: string }): string {
  if (!switched) return `This ${noun} was saved with the discount taken after GST, so its totals stay as they were.`;
  return `The discount now comes off before GST. The total changes from ${totals?.from} to ${totals?.to} when you update.`;
}

/** The note on a new invoice copied from a document that took its discount after GST. */
export function copiedDocumentNote(source: 'quotation' | 'invoice', fromTotal: string, toTotal: string): string {
  const subject = source === 'quotation' ? 'The quotation' : 'The invoice you copied';
  return `${subject} took the discount after GST (total ${fromTotal}). This invoice takes it before GST, so its total is ${toTotal}.`;
}
