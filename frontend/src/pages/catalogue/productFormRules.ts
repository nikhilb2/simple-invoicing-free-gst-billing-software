/**
 * Rules the product form applies before anything is sent, kept apart from the
 * component so they can be tested without a DOM.
 */

/**
 * The GST rates a product is normally sold at, 40 being the rate that came in with
 * GST 2.0. The form still takes any other rate under "Other rate", because older
 * products and special goods carry rates such as 0.25 or 3.
 */
export const GST_SLABS = [0, 5, 12, 18, 28, 40] as const;

export function isGstSlab(rate: string): boolean {
  return rate.trim() !== '' && GST_SLABS.some((slab) => slab === Number(rate));
}

export const GST_ZERO_NOTE =
  'You are charging no GST on this product. Choose 0% only for items that are exempt or nil-rated; otherwise pick the rate that applies.';

const HSN_PATTERN = /^(?:\d{4}|\d{6}|\d{8})$/;

export const HSN_ERROR = 'HSN/SAC code must be 4, 6 or 8 digits, numbers only. Leave it blank if you do not know it yet.';

/** What is wrong with an HSN/SAC code, in the owner's words, or '' when it is fine or blank. */
export function hsnProblem(value: string): string {
  const code = value.trim();
  return code === '' || HSN_PATTERN.test(code) ? '' : HSN_ERROR;
}

/** The HSN complaint is about the field being typed in, so editing it withdraws the complaint; other errors stay. */
export function errorAfterHsnEdit(error: string): string {
  return error === HSN_ERROR ? '' : error;
}

/**
 * The server names a failing field by its column ("Hsn sac: HSN/SAC must be 4, 6
 * or 8 digits"). This form says it in its own words instead.
 */
export function plainProductError(message: string): string {
  return /^hsn[ _]sac\b/i.test(message) && /4, 6 or 8 digits/.test(message) ? HSN_ERROR : message;
}

/**
 * Whether a new product counts stock until the owner says otherwise. A shop that
 * already counts stock for any product keeps that habit. A new company, or one
 * that only sells items it does not count, starts with counting off: a counted
 * product with nothing in stock refuses its first sale, and that is where new
 * users stopped before their first invoice (#983).
 */
export function countsStockByDefault(products: ReadonlyArray<{ maintain_inventory: boolean }>): boolean {
  return products.some((product) => product.maintain_inventory);
}

/** True when a new product will track stock yet start with none, which makes its first sale fail. */
export function startsWithNoStock(tracksStock: boolean, openingQuantity: number): boolean {
  return tracksStock && openingQuantity === 0;
}

export const NO_STOCK_WARNING =
  'You are tracking stock for this item but starting with 0, so you will not be able to sell it until you add stock. Enter how many you have now, or stop tracking stock if you do not count this item.';

export const NO_STOCK_SAVED_NOTE =
  'It has 0 in stock, so add stock before you sell it (Update stock on the invoice screen, or the catalogue).';

export const STOCK_NOT_COUNTED_NOTE =
  'Stock is not counted for this item, so you can bill it in any quantity. Count stock if you want the app to keep track of how many you have.';

/* Field messages shown under their own field when a save is tapped with
   something missing (#1153). The browser's own bubble is switched off with
   noValidate, so these are the only messages. */
export type ProductFieldKey = 'name' | 'price' | 'gst' | 'stock';

export const GST_RATE_REQUIRED = 'Choose a GST rate. Pick 0% only if you charge no GST on this product.';
export const OPENING_STOCK_REQUIRED = 'Enter how many you have now, or untick Maintain inventory.';

export type ProductFieldErrors = Partial<Record<ProductFieldKey, string>>;

/**
 * What is wrong with each field right now, in page order. `priceNoun` is the
 * word on the field's label ("selling price" on the catalogue form, "unit
 * price" in the quick-add). `stockMissing` is true only where opening stock is
 * asked for and still unanswered.
 */
export function productFieldProblems(values: {
  name: string;
  price: string;
  gstRate: string;
  priceNoun: string;
  stockMissing?: boolean;
}): ProductFieldErrors {
  const problems: ProductFieldErrors = {};
  if (!values.name.trim()) problems.name = 'Product name is required.';
  if (values.price === '' || Number.isNaN(Number(values.price))) problems.price = `Enter a ${values.priceNoun}.`;
  else if (Number(values.price) < 0) problems.price = `${values.priceNoun.charAt(0).toUpperCase()}${values.priceNoun.slice(1)} cannot be negative.`;
  if (values.gstRate.trim() === '') problems.gst = GST_RATE_REQUIRED;
  if (values.stockMissing) problems.stock = OPENING_STOCK_REQUIRED;
  return problems;
}

/**
 * The messages to show: only the fields a save was refused for, and only while
 * they are still wrong, so fixing one field clears its message and leaves the
 * others.
 */
export function shownFieldErrors(flagged: readonly ProductFieldKey[], problems: ProductFieldErrors): ProductFieldErrors {
  const shown: ProductFieldErrors = {};
  for (const key of flagged) {
    if (problems[key]) shown[key] = problems[key];
  }
  return shown;
}

/**
 * Scrolls the field's whole wrapper (label included) to just below the sticky
 * header, and focuses the control only with a fine pointer: on a phone the
 * keyboard would cover the messages under it (same rule as #1100 and #1035).
 */
export function revealFieldError(controlId: string): void {
  const control = document.getElementById(controlId);
  if (!control) return;
  const box = control.closest<HTMLElement>('.field') ?? control;
  box.style.scrollMarginTop = '104px';
  box.scrollIntoView?.({ block: 'start', behavior: 'smooth' });
  if (window.matchMedia?.('(pointer: fine)').matches) control.focus({ preventScroll: true });
}
