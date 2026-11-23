/** Words and routes for the phone layout of the invoice composer (#976). */

export const COMPOSER_PHONE_DESCRIPTION = 'Pick the customer, add items, save.';

/** Where "Saved invoices" goes: the list of saved bills, or of quotations. */
export function savedDocumentsRoute(isQuote: boolean): string {
  return isQuote ? '/quotations' : '/invoices-view';
}

export function savedDocumentsLabel(isQuote: boolean): string {
  return isQuote ? 'Saved quotations →' : 'Saved invoices →';
}

/** The muted line that replaces the Billing company card on phones. */
export function billingAsLine(companyName?: string | null): string {
  const name = companyName?.trim();
  return name ? `Billing as ${name}` : 'Billing company not set';
}

/** Left side of the sticky bar. `amount` is already formatted with its currency. */
export function totalBarLabel(amount: string): string {
  return `Total ${amount}`;
}
