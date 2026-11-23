import type { CompanyAccount, Payment, PaymentUpdate } from '../types/api';

/** Carry earlier register movements into the opening balance for this period. */
export function openingBalanceAt(
  accountOpening: number,
  payments: Pick<Payment, 'voucher_type' | 'amount' | 'account_id' | 'date'>[],
  accountId: number | null,
  fromMs: number,
): number {
  // API amounts are in two-decimal currency units; sum paise to avoid drift.
  const balancePaise = payments.reduce((balance, payment) => {
    if (payment.voucher_type !== 'receipt' && payment.voucher_type !== 'payment') return balance;
    if ((payment.account_id ?? null) !== accountId) return balance;
    if (!(new Date(payment.date).getTime() < fromMs)) return balance;
    const amountPaise = Math.round(payment.amount * 100);
    return balance + (payment.voucher_type === 'receipt' ? amountPaise : -amountPaise);
  }, Math.round(accountOpening * 100));
  return balancePaise / 100;
}

export type CashBankEditingEntry = {
  id: number;
  voucher_type: 'receipt' | 'payment';
  amount: number;
  date: string;
  notes: string;
  ledger_id: number | null;
  reference: string | null;
  mode: string | null;
};

export type CashBankEntryForm = {
  entryType: 'debit' | 'credit';
  amount: number;
  date: string;
  description: string;
};

/**
 * Payload for saving an edit from the Cash & Bank register. It deliberately
 * never carries invoice_allocations: omitting that field tells the backend
 * to leave the payment's existing allocations alone, while sending an empty
 * list would delete them. The original reference is sent back so an edit
 * does not clear it, and a ledger linked payment keeps its original mode;
 * only an account only entry (ledger_id == null) takes the account type as
 * its mode, as before.
 */
export function buildCashBankEditPayload(
  editingEntry: CashBankEditingEntry,
  selectedAccount: { id: number; account_type: string } | null,
  entryForm: CashBankEntryForm,
): PaymentUpdate {
  const voucherType = entryForm.entryType === 'debit' ? 'payment' : 'receipt';
  return {
    voucher_type: voucherType,
    amount: entryForm.amount,
    // No selected account is the Unallocated view: the entry stays unallocated.
    account_id: selectedAccount?.id ?? null,
    date: `${entryForm.date}T00:00:00`,
    mode:
      editingEntry.ledger_id != null || selectedAccount == null
        ? (editingEntry.mode ?? undefined)
        : selectedAccount.account_type,
    reference: editingEntry.reference ?? undefined,
    notes: entryForm.description.trim() || undefined,
  };
}

/**
 * The account a new receipt or payment form starts on: the first cash
 * account, else the first account, else none (Unallocated). Every new company
 * gets a "Cash" account, so a form only starts Unallocated when the company has
 * no account at all.
 */
export function defaultPaymentAccountId(
  accounts: Pick<CompanyAccount, 'id' | 'account_type'>[],
): number | null {
  const cash = accounts.find((account) => account.account_type === 'cash');
  return (cash ?? accounts[0])?.id ?? null;
}
