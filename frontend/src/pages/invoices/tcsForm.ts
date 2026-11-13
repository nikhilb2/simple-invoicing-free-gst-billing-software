/**
 * TCS state for the invoice and quotation composer (#769), kept apart from the
 * page so the rules can be tested: suggest a rate, never pick a section, send
 * nothing at all when TCS is not in play.
 */
import type { Ledger, TaxWithholdingSection } from '../../types/api';
import { suggestTcsRate, buyerHasPan, declarationCovers, roundTcsRate } from '../../utils/tcs';
import { roundMoney } from '../../utils/invoiceTotals';
import formatCurrency from '../../utils/formatting';

export type TcsFormState = {
  /** '' means no TCS. */
  sectionId: string;
  /** Null: follow the suggested rate. A string: the user (or the saved document) set it. */
  rateText: string | null;
  /** Null: follow base x rate. A string: the user typed an amount over the computed one. */
  amountText: string | null;
};

export const EMPTY_TCS_FORM: TcsFormState = { sectionId: '', rateText: null, amountText: null };

type SavedTcs = {
  tcs_section_id?: number | null;
  tcs_rate?: number | null;
  tcs_amount?: number | null;
  tcs_base_amount?: number | null;
};

/**
 * The form as a saved document or a conversion draft left it.
 *
 * - No rate (a draft whose section moved to a newer row): follow the suggestion.
 * - An amount with no base (a draft, which carries the amount only when it was typed
 *   on the quotation): typed.
 * - An amount that differs from base x rate, rounded half-up as the server does: typed.
 */
export function tcsFormFromDocument(doc: SavedTcs | null | undefined): TcsFormState {
  if (!doc || doc.tcs_section_id == null) return EMPTY_TCS_FORM;
  const rateText = doc.tcs_rate != null ? String(doc.tcs_rate) : null;
  let amountText: string | null = null;
  if (doc.tcs_amount != null) {
    if (doc.tcs_base_amount == null || doc.tcs_rate == null) {
      amountText = String(doc.tcs_amount);
    } else if (roundMoney(doc.tcs_base_amount * doc.tcs_rate / 100) !== roundMoney(doc.tcs_amount)) {
      amountText = String(doc.tcs_amount);
    }
  }
  return { sectionId: String(doc.tcs_section_id), rateText, amountText };
}

/**
 * The form for a new document copied from ``doc`` (a duplicate or a conversion).
 * A copy is a new document, so it gets TCS only while the company has TCS on:
 * the server refuses TCS on a new document otherwise.
 */
export function tcsFormForCopy(doc: SavedTcs | null | undefined, companyEnablesTcs: boolean): TcsFormState {
  return companyEnablesTcs ? tcsFormFromDocument(doc) : EMPTY_TCS_FORM;
}

export function findTcsSection(form: TcsFormState, sections: TaxWithholdingSection[] | undefined): TaxWithholdingSection | null {
  if (!form.sectionId || !sections) return null;
  return sections.find((section) => String(section.id) === form.sectionId) ?? null;
}

/** The rate in use as a number: what was typed, else the suggestion for this buyer. */
export function effectiveTcsRate(form: TcsFormState, section: TaxWithholdingSection | null, buyer: Partial<Ledger> | null | undefined): number {
  if (!section) return 0;
  if (form.rateText !== null) {
    const typed = Number(form.rateText);
    // The server keeps three places and works the amount out from them.
    return Number.isFinite(typed) ? roundTcsRate(typed) : 0;
  }
  return suggestTcsRate(section, buyer);
}

/** What to show in the rate box: the typed text, else the suggestion. */
export function tcsRateInputValue(form: TcsFormState, section: TaxWithholdingSection | null, buyer: Partial<Ledger> | null | undefined): string {
  if (form.rateText !== null) return form.rateText;
  return section ? String(suggestTcsRate(section, buyer)) : '';
}

/** The amount to hand to computeInvoiceTotals: null means base x rate. */
export function tcsTotalsInput(form: TcsFormState, section: TaxWithholdingSection | null, buyer: Partial<Ledger> | null | undefined) {
  if (!section) return null;
  const typed = form.amountText !== null && form.amountText.trim() !== '' ? Number(form.amountText) : null;
  return {
    rate: effectiveTcsRate(form, section, buyer),
    base: section.base,
    amount: typed !== null && Number.isFinite(typed) ? typed : null,
  };
}

/**
 * Payload keys. No section and no TCS on the saved document: no keys at all, so
 * a company that does not use TCS sends exactly what it sent before. A document
 * that had TCS and now has none sends a null section to remove it.
 */
export function buildTcsPayload(
  form: TcsFormState,
  section: TaxWithholdingSection | null,
  buyer: Partial<Ledger> | null | undefined,
  documentHadTcs: boolean,
): { tcs_section_id?: number | null; tcs_rate?: number; tcs_amount?: number } {
  if (!section) {
    if (form.sectionId) {
      // Chosen, but the sections for the date have not loaded (slow or failed
      // request): send what the form holds rather than strip the TCS. The server
      // still checks the section against the date.
      const rate = form.rateText !== null && Number.isFinite(Number(form.rateText)) ? roundTcsRate(Number(form.rateText)) : null;
      const amount = form.amountText !== null && form.amountText.trim() !== '' ? Number(form.amountText) : null;
      return {
        tcs_section_id: Number(form.sectionId),
        ...(rate !== null ? { tcs_rate: rate } : {}),
        ...(amount !== null && Number.isFinite(amount) ? { tcs_amount: amount } : {}),
      };
    }
    return documentHadTcs ? { tcs_section_id: null } : {};
  }
  const input = tcsTotalsInput(form, section, buyer);
  return {
    tcs_section_id: section.id,
    tcs_rate: input?.rate ?? 0,
    ...(input?.amount != null ? { tcs_amount: input.amount } : {}),
  };
}

/** A section chosen for one date may not exist on another: drop it and say so. */
export function reconcileTcsSection(
  form: TcsFormState,
  sections: TaxWithholdingSection[],
): { form: TcsFormState; cleared: boolean } {
  if (!form.sectionId || findTcsSection(form, sections)) return { form, cleared: false };
  return { form: EMPTY_TCS_FORM, cleared: true };
}

/** One-line notes under the rate box. */
export function tcsHints(section: TaxWithholdingSection | null, buyer: Partial<Ledger> | null | undefined): string[] {
  if (!section || !buyer) return [];
  const hints: string[] = [];
  if (declarationCovers(section, buyer)) hints.push('Declaration received: no TCS suggested');
  else if (!buyerHasPan(buyer)) hints.push('No PAN: higher rate under s.397(2)');
  return hints;
}

/**
 * The form after the buyer changes. A rate equal to what the old buyer was suggested
 * (a saved or copied document stores it as text) goes back to following the
 * suggestion, so the new buyer's PAN decides it. A rate the user typed that differs
 * from that suggestion stays.
 */
export function tcsFormOnBuyerChange(
  form: TcsFormState,
  section: TaxWithholdingSection | null,
  previousBuyer: Partial<Ledger> | null | undefined,
  nextBuyer: Partial<Ledger> | null | undefined,
): TcsFormState {
  if (!section || form.rateText === null || !previousBuyer || !nextBuyer) return form;
  const typed = Number(form.rateText);
  if (!Number.isFinite(typed) || roundTcsRate(typed) !== suggestTcsRate(section, previousBuyer)) return form;
  return { ...form, rateText: null };
}

/** The ₹10 lakh line of the motor vehicle section: TCS applies only above it. */
export function tcsThresholdHint(section: TaxWithholdingSection | null, invoiceValue: number): string | null {
  if (!section || section.legacy_code !== '206C(1F)' || section.threshold_single == null) return null;
  const threshold = Number(section.threshold_single);
  if (!(invoiceValue <= threshold)) return null;
  return `TCS applies only above ${formatCurrency(threshold, 'INR')} for this section; this invoice is at or below it.`;
}
