import { missingSerialsMessage } from '../../utils/missingSerialsMessage';

/**
 * Why the composer can't save, one entry per field (#1100). The same list
 * feeds the message under each field and the strip beside the save button,
 * so the two never disagree.
 */
export type ComposerProblemKind =
  | 'customer'
  | 'product'
  | 'quantity-missing'
  | 'quantity-min'
  | 'quantity-positive'
  | 'quantity-whole'
  | 'quantity-check'
  | 'price-missing'
  | 'price-min'
  | 'price-check'
  | 'discount-min'
  | 'discount-max'
  | 'discount-check'
  | 'serial';

export type ComposerProblem = { kind: ComposerProblemKind; line?: number };

export type LineField = 'product' | 'quantity' | 'price' | 'discount';

/** Order of a line's fields on the page. A line's serials come after them. */
const FIELD_RANK: Record<ComposerProblemKind, number> = {
  customer: 0,
  product: 1,
  'quantity-missing': 2,
  'quantity-min': 2,
  'quantity-positive': 2,
  'quantity-whole': 2,
  'quantity-check': 2,
  'price-missing': 3,
  'price-min': 3,
  'price-check': 3,
  'discount-min': 4,
  'discount-max': 4,
  'discount-check': 4,
  serial: 5,
};

export function quantityProblem(value: string, allowDecimal: boolean): ComposerProblemKind | null {
  if (value.trim() === '') return 'quantity-missing';
  const quantity = Number(value);
  if (!Number.isFinite(quantity)) return 'quantity-missing';
  if (allowDecimal) return quantity <= 0 ? 'quantity-positive' : null;
  if (quantity < 1) return 'quantity-min';
  if (!Number.isInteger(quantity)) return 'quantity-whole';
  return null;
}

/**
 * A blank price saves at the catalogue price. When that is 0 the line would
 * go out at ₹0, so a blank price only passes when the catalogue has one.
 */
export function priceProblem(value: string, catalogPrice: number | null): ComposerProblemKind | null {
  if (value.trim() === '') return catalogPrice === 0 ? 'price-missing' : null;
  return Number(value) < 0 ? 'price-min' : null;
}

export function discountProblem(value: string, type: string): ComposerProblemKind | null {
  if (value.trim() === '') return null;
  const discount = Number(value);
  if (discount < 0) return 'discount-min';
  if (type === 'percentage' && discount > 100) return 'discount-max';
  return null;
}

/** The fallback when the browser refuses a value none of the rules above name (say a price with three decimals). */
export function checkProblem(field: LineField): ComposerProblemKind {
  if (field === 'quantity') return 'quantity-check';
  if (field === 'price') return 'price-check';
  if (field === 'discount') return 'discount-check';
  return 'product';
}

/** The message directly under the field. Null for the kinds that have their own (customer, serial) or keep the browser's (check). */
export function fieldProblemMessage(kind: ComposerProblemKind): string | null {
  switch (kind) {
    case 'product': return 'Pick a product from the list';
    case 'quantity-missing': return 'Enter a quantity';
    case 'quantity-min': return 'Enter 1 or more';
    case 'quantity-positive': return 'Enter more than 0';
    case 'quantity-whole': return 'Use a whole number';
    case 'price-missing': return 'Enter a price';
    case 'price-min': return "Price can't be less than 0";
    case 'discount-min': return "Discount can't be below 0";
    case 'discount-max': return "Discount can't be more than 100%";
    default: return null;
  }
}

function stripSentence(problem: ComposerProblem, noun: string): string {
  const line = problem.line ?? 1;
  switch (problem.kind) {
    case 'customer': return `Choose a ${noun}`;
    case 'product': return `Pick a product for line ${line}`;
    case 'quantity-missing': return `Enter a quantity for line ${line}`;
    case 'quantity-min': return `Enter a quantity of 1 or more for line ${line}`;
    case 'quantity-positive': return `Enter a quantity of more than 0 for line ${line}`;
    case 'quantity-whole': return `Use a whole number for line ${line}`;
    case 'quantity-check': return `Check the quantity for line ${line}`;
    case 'price-missing': return `Enter a price for line ${line}`;
    case 'price-min': return `Price can't be less than 0 for line ${line}`;
    case 'price-check': return `Check the price for line ${line}`;
    case 'discount-min': return `Discount can't be below 0 for line ${line}`;
    case 'discount-max': return `Discount can't be more than 100% for line ${line}`;
    case 'discount-check': return `Check the discount for line ${line}`;
    case 'serial': return missingSerialsMessage([line]).replace(/\.$/, '');
  }
}

/** Customer first, then line by line, each line's fields left to right and its serials last. */
export function inPageOrder(problems: ComposerProblem[]): ComposerProblem[] {
  return [...problems].sort((a, b) => {
    const lineA = a.kind === 'customer' ? 0 : a.line ?? 0;
    const lineB = b.kind === 'customer' ? 0 : b.line ?? 0;
    return lineA - lineB || FIELD_RANK[a.kind] - FIELD_RANK[b.kind];
  });
}

/**
 * The text of the strip beside the save button: the first problem in page
 * order, and how many more there are. Empty when there is nothing to fix.
 * Missing serials keep #1035's wording, and when they come first, one
 * sentence names every line that needs them.
 */
export function composerSubmitReason(problems: ComposerProblem[], noun = 'customer'): string {
  if (problems.length === 0) return '';
  const ordered = inPageOrder(problems);
  const first = ordered[0];
  let sentence: string;
  let covered = 1;
  if (first.kind === 'serial') {
    const serialLines = ordered.filter((problem) => problem.kind === 'serial').map((problem) => problem.line ?? 1);
    sentence = missingSerialsMessage(serialLines).replace(/\.$/, '');
    covered = serialLines.length;
  } else {
    sentence = stripSentence(first, noun);
  }
  const more = ordered.length - covered;
  return more > 0 ? `${sentence}, and ${more} more to fix.` : `${sentence}.`;
}
