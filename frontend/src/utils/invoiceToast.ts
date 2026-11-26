import type { Product } from '../types/api';

export type InvoiceToastAction =
  | 'create'
  | 'edit'
  | 'fromQuotation'
  | 'cancel'
  | 'restore'
  | 'challanCreate'
  | 'challanEdit';

type ToastLine = { product_id: number };
type ToastProduct = Pick<Product, 'id' | 'maintain_inventory'>;

export type InvoiceToastInput = {
  action: InvoiceToastAction;
  voucherType?: 'sales' | 'purchase';
  /** The saved document's number, from the API response. */
  number: string | null | undefined;
  /** For `fromQuotation`: the number of the quotation it came from. */
  sourceNumber?: string | null;
  lines: ToastLine[] | null | undefined;
  products: ToastProduct[] | null | undefined;
};

/** What the stock sentence says, per action. */
function stockVerb(action: InvoiceToastAction, voucherType: 'sales' | 'purchase'): string {
  switch (action) {
    case 'create':
      return voucherType === 'purchase' ? 'added' : 'updated';
    case 'edit':
    case 'challanEdit':
      return 'adjusted';
    case 'fromQuotation':
    case 'challanCreate':
      return 'updated';
    case 'cancel':
      return 'put back';
    case 'restore':
      return 'taken out again';
  }
}

function firstSentence(input: InvoiceToastInput, voucherType: 'sales' | 'purchase'): string {
  const { action, number, sourceNumber } = input;
  const withNumber = (label: string) => (number ? `${label} ${number}` : label);
  switch (action) {
    case 'create':
      return `${withNumber(voucherType === 'purchase' ? 'Purchase invoice' : 'Invoice')} saved.`;
    case 'edit':
      return `${withNumber('Invoice')} updated.`;
    case 'fromQuotation':
      return `${withNumber('Invoice')} created${sourceNumber ? ` from ${sourceNumber}` : ''}.`;
    case 'cancel':
      return `${withNumber('Invoice')} cancelled.`;
    case 'restore':
      return `${withNumber('Invoice')} restored.`;
    case 'challanCreate':
      return `${withNumber('Delivery challan')} saved.`;
    case 'challanEdit':
      return `${withNumber('Delivery challan')} updated.`;
  }
}

/**
 * The toast after an invoice (or challan) is saved, cancelled or restored.
 * A stock sentence is added only when we can tell that stock really moved:
 * a line counts when its product has "Maintain inventory" on. If the lines or
 * the products are not at hand, or a line's product is unknown, only the first
 * sentence is returned, so the toast never says something that might be false.
 */
export function invoiceToastMessage(input: InvoiceToastInput): string {
  const voucherType = input.voucherType ?? 'sales';
  const first = firstSentence(input, voucherType);
  const { lines, products } = input;
  if (!lines || lines.length === 0 || !products) return first;

  let tracked = 0;
  for (const line of lines) {
    const product = products.find((p) => p.id === line.product_id);
    if (!product) return first;
    if (product.maintain_inventory) tracked += 1;
  }
  if (tracked === 0) return first;

  const total = lines.length;
  const count =
    tracked === total
      ? `${tracked} ${tracked === 1 ? 'item' : 'items'}`
      : `${tracked} of ${total} items`;
  return `${first} Stock ${stockVerb(input.action, voucherType)} for ${count}.`;
}
