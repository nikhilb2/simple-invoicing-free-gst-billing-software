import formatCurrency from './formatting';

/**
 * The one muted line the phone Invoice Feed shows in place of the "Summary of
 * all pages" panel: "Sales ₹10,080.00 · Purchases ₹157.50 · 2026-27".
 * Purchases is left out when it is zero, and " · filtered" is added when a
 * search or filter is active. Uses the same numbers as the breakdown panel.
 */
export function invoiceFeedSummaryLine(
  breakdown: { debit: number; credit: number },
  currencyCode: string,
  fyLabel: string | null | undefined,
  filtered: boolean,
): string {
  const parts = [`Sales ${formatCurrency(breakdown.debit, currencyCode)}`];
  if (breakdown.credit !== 0) {
    parts.push(`Purchases ${formatCurrency(breakdown.credit, currencyCode)}`);
  }
  if (fyLabel) parts.push(fyLabel);
  if (filtered) parts.push('filtered');
  return parts.join(' · ');
}

/** Reset only does something when a search, a filter or a product filter is set. */
export function isInvoiceFeedFiltered(search: string, activeFilterCount: number, productId: number | null): boolean {
  return search.trim() !== '' || activeFilterCount > 0 || productId !== null;
}
