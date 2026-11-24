import { describe, expect, it } from 'vitest';
import type { LedgerEntryCounts } from '../types/api';
import {
  cancelledDocumentsPhrase,
  ledgerDeletedMessage,
  ledgerDeletionWarnings,
  ledgerNameConfirmed,
} from './ledgerDeletion';

const none: LedgerEntryCounts = {
  sales_invoices: 0,
  purchase_invoices: 0,
  receipts: 0,
  payments: 0,
  opening_balance: false,
  credit_notes: 0,
  delivery_challans: 0,
  quotations: 0,
  share_links: 0,
};

describe('cancelledDocumentsPhrase', () => {
  it('counts sales and purchase invoices together and joins the rest in words', () => {
    expect(
      cancelledDocumentsPhrase({ ...none, sales_invoices: 4, purchase_invoices: 2, receipts: 3, credit_notes: 1, quotations: 2 }),
    ).toBe('6 invoices, 3 receipts, 1 credit note and 2 quotations');
  });

  it('reads one item on its own and two with "and"', () => {
    expect(cancelledDocumentsPhrase({ ...none, receipts: 1 })).toBe('1 receipt');
    expect(cancelledDocumentsPhrase({ ...none, delivery_challans: 2, opening_balance: true })).toBe(
      '2 delivery challans and the opening balance',
    );
  });

  it('is empty when nothing is live', () => {
    expect(cancelledDocumentsPhrase({ ...none, share_links: 3 })).toBe('');
  });
});

describe('ledgerDeletionWarnings', () => {
  it('says what is cancelled, that stock goes back and that it cannot be undone', () => {
    expect(ledgerDeletionWarnings({ ...none, sales_invoices: 6, receipts: 3, credit_notes: 1, quotations: 2 })).toEqual([
      'This cancels 6 invoices, 3 receipts, 1 credit note and 2 quotations for this party.',
      'Stock on these invoices goes back.',
      'The cancelled entries stay in your records and reports as cancelled.',
      "You can't undo this.",
    ]);
  });

  it('leaves out the stock line without invoices and mentions public links', () => {
    const lines = ledgerDeletionWarnings({ ...none, payments: 1, share_links: 1 });
    expect(lines).not.toContain('Stock on these invoices goes back.');
    expect(lines).toContain("1 public link to this party's statement or bills will stop working.");
  });

  it('explains a ledger whose entries are all cancelled already', () => {
    expect(ledgerDeletionWarnings(none)[0]).toBe(
      'Everything on this ledger is already cancelled. Deleting it hides the ledger from your lists.',
    );
  });
});

describe('ledgerNameConfirmed', () => {
  it('matches the name ignoring case and outer spaces', () => {
    expect(ledgerNameConfirmed('  sharma traders ', 'Sharma Traders')).toBe(true);
  });

  it('refuses a partial or different name, and an empty one', () => {
    expect(ledgerNameConfirmed('Sharma', 'Sharma Traders')).toBe(false);
    expect(ledgerNameConfirmed('', '')).toBe(false);
  });
});

describe('ledgerDeletedMessage', () => {
  it('names the ledger and what was cancelled', () => {
    expect(ledgerDeletedMessage('Sharma Traders', { ...none, sales_invoices: 2, receipts: 1 })).toBe(
      'Sharma Traders deleted. Cancelled 2 invoices and 1 receipt.',
    );
    expect(ledgerDeletedMessage('Sharma Traders', none)).toBe('Sharma Traders deleted.');
  });
});
