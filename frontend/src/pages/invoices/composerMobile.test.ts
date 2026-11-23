import { describe, expect, it } from 'vitest';
import { billingAsLine, savedDocumentsLabel, savedDocumentsRoute, totalBarLabel } from './composerMobile';

describe('composerMobile', () => {
  it('sends invoices and quotations to their own saved lists', () => {
    expect(savedDocumentsRoute(false)).toBe('/invoices-view');
    expect(savedDocumentsRoute(true)).toBe('/quotations');
    expect(savedDocumentsLabel(false)).toBe('Saved invoices →');
    expect(savedDocumentsLabel(true)).toBe('Saved quotations →');
  });

  it('names the billing company, or says it is not set', () => {
    expect(billingAsLine(' Acme Traders ')).toBe('Billing as Acme Traders');
    expect(billingAsLine('')).toBe('Billing company not set');
    expect(billingAsLine(undefined)).toBe('Billing company not set');
  });

  it('labels the sticky total', () => {
    expect(totalBarLabel('₹52.50')).toBe('Total ₹52.50');
  });
});
