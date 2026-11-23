import { describe, expect, it } from 'vitest';
import { counterpartyFor } from './counterparty';

describe('counterpartyFor', () => {
  it('speaks of a customer on sales, quotations and receipts', () => {
    for (const type of ['sales', 'quotation', 'proforma', 'receipt']) {
      const c = counterpartyFor(type);
      expect(c.label).toBe('Customer');
      expect(c.missingMessage).toBe('Choose or add a customer first');
      expect(c.emptyPlaceholder).toBe('No customers yet');
      expect(c.addLabel).toBe('+ Add a customer');
    }
  });

  it('speaks of a supplier on purchases and payments', () => {
    for (const type of ['purchase', 'payment']) {
      const c = counterpartyFor(type);
      expect(c.label).toBe('Supplier');
      expect(c.missingMessage).toBe('Choose or add a supplier first');
      expect(c.emptyPlaceholder).toBe('No suppliers yet');
      expect(c.addLabel).toBe('+ Add a supplier');
    }
  });
});
