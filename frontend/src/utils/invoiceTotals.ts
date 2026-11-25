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

export function computeInvoiceTotals(lines: InvoiceTotalLine[], {
  taxInclusive,
  invoiceDiscount = {},
  applyRoundOff = false,
  interstateSupply = true,
  tcs = null,
}: {
  taxInclusive: boolean; invoiceDiscount?: Discount; applyRoundOff?: boolean; interstateSupply?: boolean;
  /** Null or left out: no TCS, and the result has no TCS fields. */
  tcs?: TcsInput | null;
}) {
  const calculated = lines.map((line) => computeLineTotal({ ...line, taxInclusive, interstateSupply }));
  const taxableAmount = roundMoney(calculated.reduce((sum, line) => sum + line.taxableAmount, 0));
  const taxAmount = roundMoney(calculated.reduce((sum, line) => sum + line.taxAmount, 0));
  const totalAmount = roundMoney(taxableAmount + taxAmount);
  const invoiceDiscountAmount = Math.min(discountAmount(totalAmount, invoiceDiscount), totalAmount);
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
