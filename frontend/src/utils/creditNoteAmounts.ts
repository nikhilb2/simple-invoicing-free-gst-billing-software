import type { Invoice, InvoiceItem } from '../types/api';
import { roundMoney } from './invoiceTotals';

/**
 * What a credit note may credit against an invoice's lines, mirroring
 * `discounted_line_amounts(..., include_round_off=True)` in
 * backend/src/services/invoice_discounts.py and its use in
 * backend/src/services/credit_note.py (#797).
 *
 * Stored line figures are before the invoice-level discount and the round-off,
 * so a line's own `line_total` is more (or less) than the buyer was charged for it.
 */

type InvoiceAmounts = Pick<
  Invoice,
  'taxable_amount' | 'total_tax_amount' | 'round_off_amount' | 'total_amount' | 'tcs_amount' | 'igst_amount'
> & { items: Pick<InvoiceItem, 'id' | 'taxable_amount' | 'tax_amount' | 'line_total'>[] };

export type BilledLine = { taxable: number; tax: number; lineTotal: number };

export type ReturnSelection = {
  invoice: InvoiceAmounts & { id: number };
  item: Pick<InvoiceItem, 'id' | 'quantity'>;
  quantity: number;
};

const num = (value: number | null | undefined) => Number(value || 0);

/** The invoice-level discount, recovered from the totals as `invoice_discount_amount` does. */
export function invoiceDiscountAmount(invoice: InvoiceAmounts): number {
  const discount = roundMoney(
    num(invoice.taxable_amount) + num(invoice.total_tax_amount) + num(invoice.tcs_amount)
    + num(invoice.round_off_amount) - num(invoice.total_amount),
  );
  return discount > 0 ? discount : 0;
}

/** `amount` split pro-rata by `weights`; the rounding residue goes to the largest (first on a tie). */
function splitByWeight(amount: number, weights: number[]): number[] {
  const total = weights.reduce((sum, weight) => sum + weight, 0);
  if (!amount || total <= 0) return weights.map(() => 0);
  const shares = weights.map((weight) => roundMoney(amount * weight / total));
  const residue = roundMoney(amount - shares.reduce((sum, share) => sum + share, 0));
  if (residue) {
    const largest = weights.reduce((best, weight, index) => (weight > weights[best] ? index : best), 0);
    shares[largest] = roundMoney(shares[largest] + residue);
  }
  return shares;
}

const isLegacy = (item: Pick<InvoiceItem, 'taxable_amount' | 'tax_amount'>) => !num(item.taxable_amount) && !num(item.tax_amount);

/**
 * Each line's taxable value and GST after its share of the invoice discount and round-off, by item id.
 * The discount comes off taxable value and GST; the round-off, which is not tax, goes on taxable value only.
 */
export function billedLineAmounts(invoice: InvoiceAmounts): Map<number, BilledLine> {
  const taxables = invoice.items.map((item) => num(item.taxable_amount));
  const taxes = invoice.items.map((item) => num(item.tax_amount));
  const taxableTotal = taxables.reduce((sum, value) => sum + value, 0);
  const gross = taxableTotal + taxes.reduce((sum, value) => sum + value, 0);
  const discount = invoiceDiscountAmount(invoice);

  let taxableShares = taxables.map(() => 0);
  let taxShares = taxes.map(() => 0);
  if (discount && gross > 0) {
    const capped = Math.min(discount, gross);
    const taxablePart = roundMoney(capped * taxableTotal / gross);
    taxableShares = splitByWeight(taxablePart, taxables);
    taxShares = splitByWeight(roundMoney(capped - taxablePart), taxes);
  }
  const roundOffShares = gross > 0 ? splitByWeight(num(invoice.round_off_amount), taxables) : taxables.map(() => 0);

  // A discounted intrastate line keeps its GST at an even paisa so it splits into
  // equal CGST and SGST halves; the odd paisa moves to its taxable value.
  const halves = discount !== 0 && gross > 0 && !(num(invoice.igst_amount) > 0);
  const lines = new Map<number, BilledLine>();
  invoice.items.forEach((item, index) => {
    if (isLegacy(item)) {
      // A row from before the tax columns carries only its total.
      const lineTotal = roundMoney(num(item.line_total));
      lines.set(item.id, { taxable: lineTotal, tax: 0, lineTotal });
      return;
    }
    let taxable = roundMoney(taxables[index] - taxableShares[index] + roundOffShares[index]);
    let tax = roundMoney(taxes[index] - taxShares[index]);
    if (halves && tax > 0 && Math.round(tax * 100) % 2) {
      taxable = roundMoney(taxable + 0.01);
      tax = roundMoney(tax - 0.01);
    }
    lines.set(item.id, { taxable, tax, lineTotal: roundMoney(taxable + tax) });
  });
  return lines;
}

/**
 * What a return note will credit, TCS included, for lines nothing has been returned
 * from yet. Later returns can differ by a paisa of rounding, and are held to what is
 * left of each line on the server.
 */
export function returnPreviewTotal(selections: ReturnSelection[]): number {
  const billedByInvoice = new Map<number, Map<number, BilledLine>>();
  const creditedByInvoice = new Map<number, number>();
  let total = 0;

  for (const { invoice, item, quantity } of selections) {
    if (!Number.isFinite(quantity) || quantity <= 0) continue;
    if (!billedByInvoice.has(invoice.id)) billedByInvoice.set(invoice.id, billedLineAmounts(invoice));
    const line = billedByInvoice.get(invoice.id)!.get(item.id);
    if (!line) continue;

    // The share of the line returned; quantities can be fractional (0.5 kg of 0.5 kg is all of it).
    const ratio = num(item.quantity) > 0 ? quantity / num(item.quantity) : 0;
    const taxable = roundMoney(line.taxable * ratio);
    // An intrastate note splits its tax into equal CGST and SGST halves, each rounded.
    const tax = num(invoice.igst_amount) > 0
      ? roundMoney(line.tax * ratio)
      : 2 * roundMoney((line.tax / 2) * ratio);
    const credit = roundMoney(taxable + tax);
    total += credit;
    creditedByInvoice.set(invoice.id, (creditedByInvoice.get(invoice.id) || 0) + credit);
  }

  // TCS goes back in proportion to what the note credits out of what the lines billed.
  for (const [invoiceId, credited] of creditedByInvoice) {
    const invoice = selections.find((selection) => selection.invoice.id === invoiceId)!.invoice;
    const tcs = num(invoice.tcs_amount);
    if (tcs <= 0) continue;
    const whole = [...billedByInvoice.get(invoiceId)!.values()].reduce((sum, line) => sum + line.lineTotal, 0);
    if (whole <= 0) continue;
    total += roundMoney(tcs * Math.min(credited, whole) / whole);
  }

  return roundMoney(total);
}
