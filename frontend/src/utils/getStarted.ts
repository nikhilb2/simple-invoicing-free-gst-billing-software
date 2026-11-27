import type { DashboardMetrics } from '../types/api';

export type GetStartedStepId = 'address' | 'customer' | 'product' | 'invoice' | 'bank';

export type GetStartedFacts = {
  /** Ledgers on the company. Null while unknown or if the lookup failed. */
  ledgerCount: number | null;
  /** Bank accounts. Null while unknown or if the lookup failed. */
  bankAccountCount: number | null;
  /** Current profile address; unknown lookups leave the reminder unfinished. */
  companyAddress?: string | null;
};

export type GetStartedStatus = Record<GetStartedStepId, boolean>;

/** Whether a company has posted an invoice in either book. */
export function hasPostedInvoices(metrics: Pick<DashboardMetrics, 'sales'>): boolean {
  return metrics.sales.sales_invoice_count + metrics.sales.purchase_invoice_count > 0;
}

/**
 * "First run" (#1134): the active company has no sales or purchase invoice at
 * all, in any financial year, cancelled ones included. This is the same rule as
 * hasPostedInvoices (no invoice yet), but read from the invoice list total with
 * cancelled shown, because the dashboard metrics count active invoices only.
 * `hasInvoice` is null or undefined until that is known: a loading or failed
 * lookup is never a first run, so returning users see no jump.
 */
export function isFirstRun(hasInvoice: boolean | null | undefined): boolean {
  return hasInvoice === false;
}

/** URL params that pick a document to open or make. They keep today's dropdown. */
export const COMPOSER_DOCUMENT_PARAMS = ['new', 'edit', 'duplicate', 'edit_quotation', 'from_quotation', 'from_challan'] as const;

export function hasComposerDocumentParam(params: Pick<URLSearchParams, 'has'>): boolean {
  return COMPOSER_DOCUMENT_PARAMS.some((key) => params.has(key));
}

/**
 * Whether the composer shows the "Bill type: Sales invoice / Change" row in
 * place of the Voucher type dropdown. Only on first run, for a plain new sales
 * invoice: a URL that picks a document, a preselected or locked voucher type,
 * or a tap on Change all show the dropdown.
 */
export function showBillTypeRow({
  hasInvoice,
  urlPicksDocument,
  voucherType,
  locked,
  changeChosen,
}: {
  hasInvoice: boolean | null | undefined;
  urlPicksDocument: boolean;
  voucherType: string;
  locked: boolean;
  changeChosen: boolean;
}): boolean {
  return isFirstRun(hasInvoice) && !urlPicksDocument && voucherType === 'sales' && !locked && !changeChosen;
}

export function getStartedStatus(metrics: DashboardMetrics, facts: GetStartedFacts): GetStartedStatus {
  const { catalog, inventory } = metrics;
  return {
    address: Boolean(facts.companyAddress?.trim()),
    customer: (facts.ledgerCount ?? 0) > 0,
    // Stock only matters for products that track it: a services-only catalogue has
    // no tracked products and nothing to enter.
    product: catalog.total_products > 0 && (inventory.tracked_products === 0 || inventory.total_units > 0),
    invoice: hasPostedInvoices(metrics),
    bank: (facts.bankAccountCount ?? 0) > 0,
  };
}

/** Bank details are optional. A missing address remains a reminder after the first invoice. */
export function isGetStartedComplete(status: GetStartedStatus): boolean {
  return status.address && status.customer && status.product && status.invoice;
}

/**
 * The card's title. Once an invoice exists, "Set up your first invoice" reads as
 * a bug to someone who has already made one (#996 UX check), so it says what is
 * left instead: "One more step" when the address is the only required item still
 * open, "Finish setting up" otherwise. The optional bank item does not count.
 */
export function getStartedTitle(status: GetStartedStatus): string {
  if (!status.invoice) return 'Set up your first invoice';
  const onlyAddressLeft = !status.address && status.customer && status.product;
  return onlyAddressLeft ? 'One more step' : 'Finish setting up';
}

/** Whether the checklist (and the lookups behind it) should run at all. */
export function shouldRunGetStarted(metrics: DashboardMetrics | null, dismissed: boolean, hasAddress: boolean | null = true): boolean {
  return metrics !== null && !dismissed && (!hasPostedInvoices(metrics) || hasAddress === false);
}

function dismissKey(companyId: string | null): string {
  return `get_started_dismissed_${companyId ?? 'none'}`;
}

/** localStorage can be missing or throw (privacy modes); the card is not worth breaking the dashboard. */
export function readGetStartedDismissed(companyId: string | null): boolean {
  try {
    return localStorage.getItem(dismissKey(companyId)) === 'true';
  } catch {
    return false;
  }
}

export function writeGetStartedDismissed(companyId: string | null): void {
  try {
    localStorage.setItem(dismissKey(companyId), 'true');
  } catch {
    /* ignore */
  }
}

export function activeCompanyId(): string | null {
  try {
    return localStorage.getItem('active_company_id');
  } catch {
    return null;
  }
}
