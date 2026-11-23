/**
 * The words for the ledger field of the invoice composer (#962).
 *
 * New users have no ledgers yet, and "Ledger" means nothing to them. The field
 * says who it is for: a supplier on purchases and payments, a customer on the rest.
 */
export type Counterparty = {
  /** Field label. */
  label: string;
  /** Lower-case noun for sentences. */
  noun: string;
  /** Shown under the field when the form is submitted with nobody chosen. */
  missingMessage: string;
  /** Placeholder while the company has none yet. */
  emptyPlaceholder: string;
  /** The button under the error that opens the quick-add sheet. */
  addLabel: string;
};

export function counterpartyFor(voucherType: string): Counterparty {
  const supplier = voucherType === 'purchase' || voucherType === 'payment';
  const noun = supplier ? 'supplier' : 'customer';
  return {
    label: supplier ? 'Supplier' : 'Customer',
    noun,
    missingMessage: `Choose or add a ${noun} first`,
    emptyPlaceholder: `No ${noun}s yet`,
    addLabel: `+ Add a ${noun}`,
  };
}
