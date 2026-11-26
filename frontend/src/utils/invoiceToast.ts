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
      return voucherType === 'purchase' ? 'taken out' : 'put back';
    case 'restore':
      return voucherType === 'purchase' ? 'added back' : 'taken out again';
  }
}

function firstSentence(input: InvoiceToastInput, voucherType: 'sales' | 'purchase'): string {
  const { action, number, sourceNumber } = input;
  const withNumber = (label: string) => (number ? `${label} ${number}` : label);
  const invoiceLabel = voucherType === 'purchase' ? 'Purchase invoice' : 'Invoice';
  switch (action) {
    case 'create':
      return `${withNumber(invoiceLabel)} saved.`;
    case 'edit':
      return `${withNumber(invoiceLabel)} updated.`;
    case 'fromQuotation':
      return `${withNumber('Invoice')} created${sourceNumber ? ` from ${sourceNumber}` : ''}.`;
    case 'cancel':
      return `${withNumber(invoiceLabel)} cancelled.`;
    case 'restore':
      return `${withNumber(invoiceLabel)} restored.`;
    case 'challanCreate':
      return `${withNumber('Delivery challan')} saved.`;
    case 'challanEdit':
      return `${withNumber('Delivery challan')} updated.`;
  }
}

/** Actions on an existing invoice, which can be a sale or a purchase. */
const NEEDS_VOUCHER_TYPE: InvoiceToastAction[] = ['edit', 'cancel', 'restore'];

/**
 * "2 items", "1 item" or "1 of 2 items": how many lines move stock, i.e. whose
 * product has "Maintain inventory" on. Null when that can't be told (lines or
 * products missing, or a line's product unknown) or when no line moves stock.
 */
export function trackedStockCount(
  lines: ToastLine[] | null | undefined,
  products: ToastProduct[] | null | undefined,
): string | null {
  if (!lines || lines.length === 0 || !products) return null;
  let tracked = 0;
  for (const line of lines) {
    const product = products.find((p) => p.id === line.product_id);
    if (!product) return null;
    if (product.maintain_inventory) tracked += 1;
  }
  if (tracked === 0) return null;
  const total = lines.length;
  return tracked === total
    ? `${tracked} ${tracked === 1 ? 'item' : 'items'}`
    : `${tracked} of ${total} items`;
}

/**
 * The toast after an invoice (or challan) is saved, cancelled or restored.
 * A stock sentence is added only when we can tell that stock really moved:
 * a line counts when its product has "Maintain inventory" on. If the lines or
 * the products are not at hand, or a line's product is unknown, only the first
 * sentence is returned, so the toast never says something that might be false.
 * Edit, cancel and restore move stock in opposite directions for sales and
 * purchases, so without a voucher type they also return only the first sentence.
 */
export function invoiceToastMessage(input: InvoiceToastInput): string {
  const voucherType = input.voucherType ?? 'sales';
  const first = firstSentence(input, voucherType);
  if (!input.voucherType && NEEDS_VOUCHER_TYPE.includes(input.action)) return first;
  const count = trackedStockCount(input.lines, input.products);
  if (!count) return first;
  return `${first} Stock ${stockVerb(input.action, voucherType)} for ${count}.`;
}

/** The cancel confirm dialog's text. It mentions stock only when stock will really move. */
export function invoiceCancelConfirmMessage(input: {
  number: string | null | undefined;
  voucherType?: 'sales' | 'purchase' | null;
  lines: ToastLine[] | null | undefined;
  products: ToastProduct[] | null | undefined;
}): string {
  const parts = [input.number ? `Cancel invoice ${input.number}?` : 'Cancel this invoice?'];
  const count = input.voucherType ? trackedStockCount(input.lines, input.products) : null;
  if (count) {
    parts.push(`Stock will be ${input.voucherType === 'purchase' ? 'taken out' : 'put back'} for ${count}.`);
  }
  parts.push('You can still see it when you show cancelled invoices.');
  return parts.join(' ');
}
