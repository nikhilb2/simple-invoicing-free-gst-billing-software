import type { DiscountMode } from '../types/api';

/** Preview arithmetic follows InvoiceProcessor and document_totals on the server. */
export type InvoiceTotalLine = {
  unitPrice: number;
  quantity: number;
  gstRate: number;
  discountType?: string;
  discountValue?: number;
};

type Discount = { type?: string; value?: number };

/**
 * TCS on the invoice (#769), mirroring document_totals._apply_tcs and services/tcs.py.
 * `rate` is a percentage. `amount`, when set, is what the user typed as collected and
 * wins over base x rate. `base` is the section's base column: 'gross' is taxable + GST
 * - invoice discount; 'taxable' is the pre-GST share of that.
 */
export type TcsInput = { rate: number; base?: 'gross' | 'taxable'; amount?: number | null };

export function tcsBaseAmount(afterDiscountTotal: number, totalAmount: number, taxableAmount: number, base: TcsInput['base'] = 'gross'): number {
  if (base !== 'taxable') return roundMoney(afterDiscountTotal);
  if (totalAmount <= 0) return 0;
  return roundMoney(afterDiscountTotal * taxableAmount / totalAmount);
}

/** ROUND_HALF_UP, including negative values; tolerate binary error at a tie. */
export function roundMoney(value: number): number {
  const magnitude = Math.abs(value);
  const rounded = Math.round((magnitude + 4 * Number.EPSILON * Math.max(1, magnitude)) * 100) / 100;
  return rounded === 0 ? 0 : Math.sign(value) * rounded;
}

function discountAmount(total: number, { type, value }: Discount): number {
  if (!type || value == null || !Number.isFinite(value) || value <= 0) return 0;
  return type === 'percentage' ? roundMoney(total * value / 100) : roundMoney(value);
}

export function computeLineTotal({
  unitPrice, quantity, gstRate, taxInclusive, discountType, discountValue, interstateSupply = true,
}: InvoiceTotalLine & { taxInclusive: boolean; interstateSupply?: boolean }) {
  if (![unitPrice, quantity, gstRate].every(Number.isFinite)) {
    return { taxableAmount: 0, taxAmount: 0, lineTotal: 0 };
  }
  let lineTotal = roundMoney(unitPrice * quantity);
  let taxableAmount = taxInclusive ? roundMoney(lineTotal / (1 + gstRate / 100)) : lineTotal;
  let taxAmount = taxInclusive
    ? roundMoney(lineTotal - taxableAmount)
    : roundMoney(taxableAmount * gstRate / 100);
  if (!taxInclusive) lineTotal = roundMoney(taxableAmount + taxAmount);

  const discount = discountAmount(taxableAmount, { type: discountType, value: discountValue });
  const appliedDiscount = discountType === 'percentage' ? discount : Math.min(discount, taxableAmount);
  if (appliedDiscount > 0) {
    taxableAmount = roundMoney(taxableAmount - appliedDiscount);
    if (taxInclusive) {
      lineTotal = roundMoney(taxableAmount * (1 + gstRate / 100));
      taxAmount = roundMoney(lineTotal - taxableAmount);
    } else {
      taxAmount = roundMoney(taxableAmount * gstRate / 100);
      lineTotal = roundMoney(taxableAmount + taxAmount);
    }
  }
  if (!interstateSupply) {
    // Match the backend: round both GST halves independently.
    // Inclusive prices retain their gross total; the taxable base adjusts.
    taxAmount = roundMoney(2 * roundMoney(taxableAmount * (gstRate / 2) / 100));
    if (taxInclusive) taxableAmount = roundMoney(lineTotal - taxAmount);
    else lineTotal = roundMoney(taxableAmount + taxAmount);
  }
  return { taxableAmount, taxAmount, lineTotal };
}

export type { DiscountMode };

/* Exact paise arithmetic for the before-GST share, as the server's Decimal does it.
   Binary floats can land a hair under a half paisa (84.662 is fine, 0.125 x 3 is not). */
function decimalParts(value: number): { digits: bigint; scale: bigint } {
  let text = String(value);
  if (/e/i.test(text)) text = value.toFixed(20);
  const negative = text.startsWith('-');
  const [whole, fraction = ''] = (negative ? text.slice(1) : text).split('.');
  const digits = BigInt(whole + fraction) * (negative ? -1n : 1n);
  return { digits, scale: 10n ** BigInt(fraction.length) };
}

/** numerator / denominator rounded half-up (away from zero), as ROUND_HALF_UP. */
function divideHalfUp(numerator: bigint, denominator: bigint): bigint {
  const negative = (numerator < 0n) !== (denominator < 0n);
  const n = numerator < 0n ? -numerator : numerator;
  const d = denominator < 0n ? -denominator : denominator;
  const quotient = (2n * n + d) / (2n * d);
  return negative ? -quotient : quotient;
}

const toPaise = (amount: number) => BigInt(Math.round(amount * 100));
const fromPaise = (paise: bigint) => Number(paise) / 100;

/** paise x value / (100 x divisor), to the paisa: money(amount x value / 100) on the server. */
function percentOf(paise: bigint, value: number, divisor = 1n): bigint {
  const { digits, scale } = decimalParts(value);
  return divideHalfUp(paise * digits, 100n * scale * divisor);
}

/** The before-GST bill discount on a subtotal: % of it, or the flat amount, to the paisa. */
export function billDiscountAmount(subtotal: number, { type, value }: Discount): number {
  if (!type || value == null || !Number.isFinite(value) || value <= 0) return 0;
  if (type === 'percentage') return fromPaise(percentOf(toPaise(subtotal), value));
  const { digits, scale } = decimalParts(value);
  return fromPaise(divideHalfUp(digits * 100n, scale));
}

/**
 * Shares a discount across lines by their taxable value, as the server's
 * `_split_by_weight`: each share rounded half-up to the paisa, and what is left
 * over put on the largest line (the first on a tie), so they add up exactly.
 */
export function shareByWeight(amount: number, weights: number[]): number[] {
  const amountPaise = toPaise(amount);
  const weightPaise = weights.map(toPaise);
  const total = weightPaise.reduce((sum, weight) => sum + weight, 0n);
  if (amountPaise === 0n || total <= 0n) return weights.map(() => 0);
  const shares = weightPaise.map((weight) => divideHalfUp(amountPaise * weight, total));
  const residue = amountPaise - shares.reduce((sum, share) => sum + share, 0n);
  if (residue !== 0n) {
    let largest = 0;
    weightPaise.forEach((weight, index) => { if (weight > weightPaise[largest]) largest = index; });
    shares[largest] += residue;
  }
  return shares.map(fromPaise);
}

/** CGST and SGST (each half, rounded at half the rate, so equal), or IGST, of a GST total. */
export function gstHeads(taxAmount: number, interstateSupply: boolean) {
  if (interstateSupply) return { cgstAmount: 0, sgstAmount: 0, igstAmount: roundMoney(taxAmount) };
  const half = roundMoney(taxAmount / 2);
  return { cgstAmount: half, sgstAmount: half, igstAmount: 0 };
}

type LineResult = ReturnType<typeof computeLineTotal>;

/**
 * A line after its share of a before-GST bill discount, as share_bill_discount on the
 * server: GST worked out again on the reduced taxable value like an ex-GST line,
 * CGST and SGST each at half the rate. Inclusive prices too: the share comes off the
 * ex-GST value.
 */
function lineAfterShare(line: LineResult, gstRate: number, share: number, interstateSupply: boolean): LineResult {
  if (share === 0) return line;
  const taxable = toPaise(line.taxableAmount) - toPaise(share);
  const rate = Number.isFinite(gstRate) ? gstRate : 0;
  const tax = interstateSupply ? percentOf(taxable, rate) : 2n * percentOf(taxable, rate, 2n);
  return { taxableAmount: fromPaise(taxable), taxAmount: fromPaise(tax), lineTotal: fromPaise(taxable + tax) };
}

export function computeInvoiceTotals(lines: InvoiceTotalLine[], {
  taxInclusive,
  invoiceDiscount = {},
  discountMode = 'after_tax',
  applyRoundOff = false,
  interstateSupply = true,
  tcs = null,
}: {
  taxInclusive: boolean; invoiceDiscount?: Discount; applyRoundOff?: boolean; interstateSupply?: boolean;
  /**
   * 'before_tax' (#1154, every new document): the bill discount comes off the subtotal
   * and is shared over the lines before GST, and the result also carries `subtotal`,
   * `billDiscountAmount`, `billDiscountShares` and `billDiscountTooLarge`. 'after_tax'
   * (the default here, documents saved before #1154): off taxable + GST at the end.
   */
  discountMode?: DiscountMode;
  /** Null or left out: no TCS, and the result has no TCS fields. */
  tcs?: TcsInput | null;
}) {
  let calculated = lines.map((line) => computeLineTotal({ ...line, taxInclusive, interstateSupply }));
  let beforeTaxFields: {
    subtotal: number; billDiscountAmount: number; billDiscountShares: number[]; billDiscountTooLarge: boolean;
  } | undefined;
  if (discountMode === 'before_tax') {
    const subtotal = roundMoney(calculated.reduce((sum, line) => sum + line.taxableAmount, 0));
    const asked = billDiscountAmount(subtotal, invoiceDiscount);
    // The server refuses a discount over the subtotal; the preview leaves it out
    // (and says so) rather than show negative figures.
    const tooLarge = asked > subtotal;
    const discount = tooLarge ? 0 : asked;
    const shares = shareByWeight(discount, calculated.map((line) => line.taxableAmount));
    calculated = calculated.map((line, index) => lineAfterShare(line, lines[index].gstRate, shares[index], interstateSupply));
    beforeTaxFields = { subtotal, billDiscountAmount: discount, billDiscountShares: shares, billDiscountTooLarge: tooLarge };
  }
  const taxableAmount = roundMoney(calculated.reduce((sum, line) => sum + line.taxableAmount, 0));
  const taxAmount = roundMoney(calculated.reduce((sum, line) => sum + line.taxAmount, 0));
  const totalAmount = roundMoney(taxableAmount + taxAmount);
  // Before GST the discount is already in the lines: nothing more comes off here.
  const invoiceDiscountAmount = beforeTaxFields
    ? 0
    : Math.min(discountAmount(totalAmount, invoiceDiscount), totalAmount);
  const afterDiscountTotal = roundMoney(totalAmount - invoiceDiscountAmount);
  // TCS goes on after the invoice discount and before the round-off, so the total
  // is still a whole rupee: total = taxable + tax - discount + tcs + round-off.
  let tcsFields: { tcsBaseAmount: number; tcsAmount: number } | undefined;
  let beforeRoundOff = afterDiscountTotal;
  if (tcs) {
    const tcsBase = tcsBaseAmount(afterDiscountTotal, totalAmount, taxableAmount, tcs.base);
    const rate = Number.isFinite(tcs.rate) ? tcs.rate : 0;
    const tcsAmount = tcs.amount != null && Number.isFinite(tcs.amount)
      ? roundMoney(tcs.amount)
      : roundMoney(tcsBase * rate / 100);
    tcsFields = { tcsBaseAmount: tcsBase, tcsAmount };
    beforeRoundOff = roundMoney(afterDiscountTotal + tcsAmount);
  }
  const total = applyRoundOff
    ? Math.sign(beforeRoundOff) * Math.round(Math.abs(beforeRoundOff))
    : beforeRoundOff;
  return {
    taxableAmount, taxAmount, totalAmount, invoiceDiscountAmount, afterDiscountTotal,
    ...tcsFields,
    ...beforeTaxFields,
    roundOffAmount: roundMoney(total - beforeRoundOff), total,
  };
}

export const PRICE_INCLUDES_GST_LABEL = 'Price already includes GST';

/** Column label for the unit price input on an invoice line. */
export function priceColumnLabel(taxInclusive: boolean): string {
  return taxInclusive ? 'Price (incl. GST)' : 'Price';
}

/**
 * One-line example of what the "Price already includes GST" choice does, using the first
 * line's unit price and the product's GST rate. Quantity and line discount are left out on
 * purpose: the sentence describes the price itself, so it stays true whatever the discount.
 * Returns null until there is both a price and a GST rate. Uses `computeLineTotal` for the split.
 */
export function priceIncludesGstExample({
  unitPrice, gstRate, taxInclusive, interstateSupply = true, format,
}: {
  unitPrice: number; gstRate: number; taxInclusive: boolean; interstateSupply?: boolean;
  format: (value: number) => string;
}): string | null {
  if (!Number.isFinite(unitPrice) || !Number.isFinite(gstRate) || unitPrice <= 0 || gstRate <= 0) return null;
  const { taxableAmount, taxAmount, lineTotal } = computeLineTotal({
    unitPrice, quantity: 1, gstRate, taxInclusive, interstateSupply,
  });
  return taxInclusive
    ? `Price ${format(lineTotal)} with ${gstRate}% GST = ${format(taxableAmount)} taxable value + ${format(taxAmount)} GST`
    : `Price ${format(taxableAmount)} + ${format(taxAmount)} GST = ${format(lineTotal)} total`;
}
