/**
 * TCS state for the invoice and quotation composer (#769), kept apart from the
 * page so the rules can be tested: suggest a rate, never pick a section, send
 * nothing at all when TCS is not in play.
 */
import type { Ledger, TaxWithholdingSection } from '../../types/api';
import { suggestTcsRate, buyerHasPan, declarationCovers } from '../../utils/tcs';

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

/** The form as a saved document left it. An amount that differs from base x rate was typed by hand. */
export function tcsFormFromDocument(doc: SavedTcs | null | undefined): TcsFormState {
  if (!doc || doc.tcs_section_id == null) return EMPTY_TCS_FORM;
  const rate = doc.tcs_rate ?? 0;
  let amountText: string | null = null;
  if (doc.tcs_amount != null && doc.tcs_base_amount != null) {
    const computed = Math.round((doc.tcs_base_amount * rate / 100 + Number.EPSILON) * 100) / 100;
    if (Math.abs(computed - doc.tcs_amount) > 0.005) amountText = String(doc.tcs_amount);
  }
  return { sectionId: String(doc.tcs_section_id), rateText: String(rate), amountText };
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
    return Number.isFinite(typed) ? typed : 0;
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
  if (!section) return documentHadTcs ? { tcs_section_id: null } : {};
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
