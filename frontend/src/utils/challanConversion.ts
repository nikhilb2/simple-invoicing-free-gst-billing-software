import { getApiErrorCode, getApiErrorMessage } from '../api/client';
import type { Product } from '../types/api';
import { formatDate } from './formatting';

/**
 * "DC-2026-004 dated 16-11-2026": how the composer and invoice view name the challan an
 * invoice was made from. The invoice PDF prints the same reference from the invoice's
 * link to the challan, so it is not copied into the editable reference notes.
 */
export function challanReferenceText(challanNumber: string, challanDate: string | null | undefined): string {
  return challanDate ? `${challanNumber} dated ${formatDate(challanDate)}` : challanNumber;
}

export type ChallanAlreadyInvoiced = { message: string; invoiceNumber: string | null };

/**
 * The "already invoiced" refusal of a challan conversion, or null for any other error.
 *
 * The server sends it both when the draft is loaded (a stale link or bookmark) and when the
 * invoice is saved (someone got there first), so both paths show the same banner and link.
 */
export function readChallanAlreadyInvoiced(error: unknown): ChallanAlreadyInvoiced | null {
  if (getApiErrorCode(error) !== 'challan_already_invoiced') return null;
  const detail = (error as { response?: { data?: { detail?: { invoice_number?: unknown } } } }).response?.data?.detail;
  const invoiceNumber = typeof detail?.invoice_number === 'string' && detail.invoice_number ? detail.invoice_number : null;
  return {
    message: getApiErrorMessage(error, 'This delivery challan was already invoiced.'),
    invoiceNumber,
  };
}

export type ChallanQuantityNote = {
  productId: number;
  challanQuantity: number;
  invoiceQuantity: number;
  /** Always positive. */
  difference: number;
  direction: 'back_to_stock' | 'more_out';
  message: string;
};

/** Quantities are kept to 3 decimals; this drops floating-point noise such as 0.1 + 0.2. */
function roundQuantity(value: number): number {
  return Math.round(value * 1000) / 1000;
}

/** Up to 3 decimals, trailing zeros dropped: 2.5, 20, 0.125. */
export function formatNoteQuantity(value: number): string {
  return String(Number(roundQuantity(value).toFixed(3)));
}

/**
 * How the invoice's quantities differ from the challan's, per product.
 *
 * The challan's goods are already out of stock, so only the difference moves stock when the
 * invoice is saved. Smaller invoice quantities put goods back; larger ones take more out.
 * Only products on the challan are compared, and products that do not keep stock are skipped.
 */
export function challanQuantityNotes(
  challanLines: { product_id: number; product_name: string | null; quantity: number }[],
  invoiceLines: { productId: number; quantity: number }[],
  products: Pick<Product, 'id' | 'name' | 'maintain_inventory'>[],
): ChallanQuantityNote[] {
  const challanTotals = new Map<number, number>();
  const challanNames = new Map<number, string | null>();
  for (const line of challanLines) {
    challanTotals.set(line.product_id, roundQuantity((challanTotals.get(line.product_id) ?? 0) + line.quantity));
    if (!challanNames.has(line.product_id)) challanNames.set(line.product_id, line.product_name);
  }

  const invoiceTotals = new Map<number, number>();
  for (const line of invoiceLines) {
    const quantity = Number.isNaN(line.quantity) ? 0 : line.quantity;
    invoiceTotals.set(line.productId, roundQuantity((invoiceTotals.get(line.productId) ?? 0) + quantity));
  }

  const notes: ChallanQuantityNote[] = [];
  for (const [productId, challanQuantity] of challanTotals) {
    const product = products.find((entry) => entry.id === productId);
    if (product && !product.maintain_inventory) continue;

    const invoiceQuantity = invoiceTotals.get(productId) ?? 0;
    if (invoiceQuantity === challanQuantity) continue;

    const name = product?.name || challanNames.get(productId) || `Product ${productId}`;
    const difference = Math.abs(challanQuantity - invoiceQuantity);
    const direction = invoiceQuantity < challanQuantity ? 'back_to_stock' : 'more_out';
    const head = `${name}: challan ${formatNoteQuantity(challanQuantity)}, invoicing ${formatNoteQuantity(invoiceQuantity)}.`;
    const message = direction === 'back_to_stock'
      ? `${head} ${formatNoteQuantity(difference)} will be added back to stock. Make sure they're returned.`
      : `${head} ${formatNoteQuantity(difference)} more will be reduced from stock.`;
    notes.push({ productId, challanQuantity, invoiceQuantity, difference, direction, message });
  }
  return notes;
}
