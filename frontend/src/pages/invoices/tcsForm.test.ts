import { describe, expect, it } from 'vitest';
import type { TaxWithholdingSection } from '../../types/api';
import {
  EMPTY_TCS_FORM, buildTcsPayload, effectiveTcsRate, findTcsSection, reconcileTcsSection,
  tcsFormForCopy, tcsFormFromDocument, tcsFormOnBuyerChange, tcsHints, tcsThresholdHint, tcsRateInputValue, tcsTotalsInput,
} from './tcsForm';

const section: TaxWithholdingSection = {
  id: 7, kind: 'tcs', act: 1961, section_ref: '394(1) Sl. No. 4', legacy_code: '206C(1)', nature: 'Scrap',
  rate_individual_huf: 1, rate_other: 1, rate_no_pan: 5, threshold_single: null, threshold_aggregate: null,
  threshold_note: null, base: 'gross', effective_from: '2024-04-01', effective_to: null,
};
const withPan = { gst: '27ABCDE1234F1Z5', pan: 'ABCDE1234F' };
const noPan = { gst: '', pan: '' };
const chosen = { ...EMPTY_TCS_FORM, sectionId: '7' };

describe('tcsForm', () => {
  it('suggests by PAN and declaration', () => {
    expect(effectiveTcsRate(chosen, section, withPan)).toBe(1);
    expect(effectiveTcsRate(chosen, section, noPan)).toBe(5);
    expect(effectiveTcsRate(chosen, section, { ...withPan, tcs_declaration_received: true })).toBe(0);
    expect(tcsRateInputValue(chosen, section, noPan)).toBe('5');
  });

  it('keeps a typed rate when the buyer changes', () => {
    const typed = { ...chosen, rateText: '2' };
    expect(effectiveTcsRate(typed, section, noPan)).toBe(2);
  });

  it('sends no keys without a section, or null when the document had TCS', () => {
    expect(buildTcsPayload(EMPTY_TCS_FORM, null, withPan, false)).toEqual({});
    expect(buildTcsPayload(EMPTY_TCS_FORM, null, withPan, true)).toEqual({ tcs_section_id: null });
  });

  it('sends tcs_amount only when overridden', () => {
    expect(buildTcsPayload(chosen, section, withPan, false)).toEqual({ tcs_section_id: 7, tcs_rate: 1 });
    expect(buildTcsPayload({ ...chosen, amountText: '12.5' }, section, withPan, false))
      .toEqual({ tcs_section_id: 7, tcs_rate: 1, tcs_amount: 12.5 });
    expect(tcsTotalsInput({ ...chosen, amountText: '' }, section, withPan)?.amount).toBeNull();
    expect(tcsTotalsInput(EMPTY_TCS_FORM, null, withPan)).toBeNull();
  });

  it('clears a section missing from the date list', () => {
    expect(reconcileTcsSection(chosen, [{ ...section, id: 8 }])).toEqual({ form: EMPTY_TCS_FORM, cleared: true });
    expect(reconcileTcsSection(chosen, [section]).cleared).toBe(false);
    expect(findTcsSection(chosen, [section])).toBe(section);
  });

  it('loads a saved document and detects a hand-typed amount', () => {
    expect(tcsFormFromDocument({ tcs_section_id: null })).toEqual(EMPTY_TCS_FORM);
    expect(tcsFormFromDocument({ tcs_section_id: 7, tcs_rate: 1, tcs_base_amount: 1000, tcs_amount: 10 }))
      .toEqual({ sectionId: '7', rateText: '1', amountText: null });
    expect(tcsFormFromDocument({ tcs_section_id: 7, tcs_rate: 1, tcs_base_amount: 1000, tcs_amount: 15 }).amountText).toBe('15');
  });

  it('rounds half-up like the server, so a saved amount at a binary tie is not taken as typed', () => {
    // 1001.25 x 2% = 20.025: the server stores 20.03.
    expect(tcsFormFromDocument({ tcs_section_id: 7, tcs_rate: 2, tcs_base_amount: 1001.25, tcs_amount: 20.03 }).amountText)
      .toBeNull();
  });

  it('loads a conversion draft: no rate follows the suggestion, an amount without a base was typed', () => {
    // A quotation from before 1 April 2026 converted today: the section moved, so the draft has no rate.
    const moved = tcsFormFromDocument({ tcs_section_id: 7 });
    expect(moved).toEqual({ sectionId: '7', rateText: null, amountText: null });
    expect(effectiveTcsRate(moved, section, withPan)).toBe(1);
    // The quotation's typed 2000 against a computed 2360 travels in the draft without a base.
    expect(tcsFormFromDocument({ tcs_section_id: 7, tcs_rate: 2, tcs_amount: 2000 }).amountText).toBe('2000');
  });

  it('resends the chosen TCS while the sections for the date have not loaded', () => {
    const saved = tcsFormFromDocument({ tcs_section_id: 7, tcs_rate: 2, tcs_base_amount: 1000, tcs_amount: 25 });
    expect(buildTcsPayload(saved, null, withPan, true)).toEqual({ tcs_section_id: 7, tcs_rate: 2, tcs_amount: 25 });
    expect(buildTcsPayload({ ...chosen }, null, withPan, true)).toEqual({ tcs_section_id: 7 });
  });

  it('uses the rate at three places, as the server stores it', () => {
    expect(effectiveTcsRate({ ...chosen, rateText: '1.2345' }, section, withPan)).toBe(1.235);
    expect(buildTcsPayload({ ...chosen, rateText: '1.2345' }, section, withPan, false)).toEqual({ tcs_section_id: 7, tcs_rate: 1.235 });
  });

  it('hints about PAN and declaration', () => {
    expect(tcsHints(section, noPan)).toEqual(['No PAN: higher rate under s.397(2)']);
    expect(tcsHints(section, { ...withPan, tcs_declaration_received: true })).toEqual(['Declaration received: no TCS suggested']);
    expect(tcsHints(section, withPan)).toEqual([]);
    expect(tcsHints(section, null)).toEqual([]);
  });
});

describe('copies', () => {
  const saved = { tcs_section_id: 7, tcs_rate: 2, tcs_base_amount: 1000, tcs_amount: 20 };

  it('a duplicate keeps TCS only while the company has TCS on', () => {
    expect(tcsFormForCopy(saved, true)).toEqual({ sectionId: '7', rateText: '2', amountText: null });
    expect(tcsFormForCopy(saved, false)).toEqual(EMPTY_TCS_FORM);
    // And with nothing chosen, a new document sends no TCS keys at all.
    expect(buildTcsPayload(tcsFormForCopy(saved, false), null, null, false)).toEqual({});
  });
});

describe('tcsForm buyer change and threshold', () => {
  it('re-suggests when the stored rate was only the old buyer suggestion', () => {
    const saved = { ...chosen, rateText: '1' };
    expect(tcsFormOnBuyerChange(saved, section, withPan, noPan)).toEqual({ ...chosen, rateText: null });
    expect(effectiveTcsRate(tcsFormOnBuyerChange(saved, section, withPan, noPan), section, noPan)).toBe(5);
  });

  it('leaves a rate typed by hand alone', () => {
    const typed = { ...chosen, rateText: '3' };
    expect(tcsFormOnBuyerChange(typed, section, withPan, noPan)).toBe(typed);
    expect(tcsFormOnBuyerChange(chosen, section, withPan, noPan)).toBe(chosen);
  });

  it('hints that a motor vehicle sale at or below 10 lakh carries no TCS', () => {
    const car = { ...section, legacy_code: '206C(1F)', threshold_single: 1000000 };
    expect(tcsThresholdHint(car, 1000000)).toContain('only above');
    expect(tcsThresholdHint(car, 500000)).toContain('10,00,000');
    expect(tcsThresholdHint(car, 1000001)).toBeNull();
    expect(tcsThresholdHint(section, 500000)).toBeNull();
  });
});

