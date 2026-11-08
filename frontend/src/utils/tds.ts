import type { OutstandingInvoice, PaymentInvoiceAllocation, TaxWithholdingSection } from '../types/api';

const paise = (value: number | string | null | undefined): number => Math.round(Number(value || 0) * 100);

/** The date TDS sections are judged on: the earlier of the invoice date and the payment date, as YYYY-MM-DD. */
export function deductionDate(invoiceDate: string, paymentDate: string | null | undefined): string {
  const invoice = (invoiceDate || '').slice(0, 10);
  const payment = (paymentDate || '').slice(0, 10);
  if (!payment) return invoice;
  if (!invoice) return payment;
  return invoice <= payment ? invoice : payment;
}

/** Cash plus TDS: how much of an invoice this allocation settles. */
export function settledAmount(allocated: number | string | null | undefined, tds: number | string | null | undefined): number {
  return (paise(allocated) + paise(tds)) / 100;
}

/** True when cash + TDS covers the invoice's remaining amount exactly (to the paisa). */
export function isFullySettled(
  remaining: number,
  allocated: number | string | null | undefined,
  tds: number | string | null | undefined,
): boolean {
  return paise(remaining) > 0 && paise(allocated) + paise(tds) === paise(remaining);
}

/** By how much cash + TDS exceeds the remaining amount; 0 when it does not. */
export function overSettlement(
  remaining: number,
  allocated: number | string | null | undefined,
  tds: number | string | null | undefined,
): number {
  const over = paise(allocated) + paise(tds) - paise(remaining);
  return over > 0 ? over / 100 : 0;
}

export function totalTds(allocations: Array<{ tds_amount?: number | string | null }> | undefined): number {
  return (allocations ?? []).reduce((sum, a) => sum + paise(a.tds_amount), 0) / 100;
}

/**
 * Checks each allocation that carries TDS: a section is required, and cash + TDS
 * may not exceed the invoice's remaining amount. Returns an error or null.
 */
export function validateTdsAllocations(
  allocations: PaymentInvoiceAllocation[] | undefined,
  outstanding: Array<Pick<OutstandingInvoice, 'id' | 'remaining_amount' | 'invoice_number'>>,
): string | null {
  for (const allocation of allocations ?? []) {
    const label = allocation.invoice_number ?? `invoice ${allocation.invoice_id}`;
    const tds = Number(allocation.tds_amount || 0);
    if (!Number.isFinite(tds) || tds < 0) return `TDS for ${label} cannot be negative`;
    if (tds > 0 && !allocation.tds_section_id) return `Choose the TDS section for ${label}`;
    const invoice = outstanding.find((item) => item.id === allocation.invoice_id);
    if (invoice && overSettlement(invoice.remaining_amount, allocation.allocated_amount, tds) > 0) {
      return `Cash and TDS for ${label} exceed the amount remaining on it`;
    }
  }
  return null;
}

type SectionLabelInput = Pick<TaxWithholdingSection, 'section_ref' | 'nature' | 'rate_individual_huf' | 'rate_other'>;

/** e.g. "s.393(1) Sl. No. 6(iii) — Professional fees (10%)". */
export function sectionOptionLabel(section: SectionLabelInput): string {
  const ref = `s.${section.section_ref}`;
  const rates = [section.rate_individual_huf, section.rate_other].filter((r): r is number => typeof r === 'number');
  const rate = rates.length === 0
    ? ''
    : rates[0] === rates[rates.length - 1] || rates.length === 1
      ? ` (${rates[0]}%)`
      : ` (${rates[0]}% / ${rates[1]}%)`;
  return `${ref} — ${section.nature}${rate}`;
}

/**
 * Whether an allocation row shows the TDS fields. Receipts always may; a
 * payment only when the company deducts TDS on purchases, or when the row
 * already carries TDS (so it stays visible, and removable, after the setting
 * is turned off).
 */
export function showTdsFields(
  voucherType: string,
  enablePurchaseTds: boolean | undefined,
  allocation: Pick<PaymentInvoiceAllocation, 'tds_amount'> | undefined,
): boolean {
  if (voucherType === 'receipt') return true;
  if (voucherType !== 'payment') return false;
  return Boolean(enablePurchaseTds) || Number(allocation?.tds_amount || 0) > 0;
}

/** The enable_purchase_tds value to save: never on without a TAN (the server refuses it). */
export function purchaseTdsSetting(enabled: boolean | undefined, tan: string | null | undefined): boolean {
  return Boolean(enabled) && Boolean((tan || '').trim());
}
