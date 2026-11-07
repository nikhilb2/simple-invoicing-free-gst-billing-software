import { describe, expect, it } from 'vitest';
import type { TaxWithholdingSection } from '../../types/api';
import {
  EMPTY_TCS_FORM, buildTcsPayload, effectiveTcsRate, findTcsSection, reconcileTcsSection,
  tcsFormFromDocument, tcsHints, tcsRateInputValue, tcsTotalsInput,
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
    expect(tcsFormFromDocument({ tcs_section_id: 7, tcs_rate: 1, tcs_amount: 15 }).amountText).toBeNull();
  });

  it('hints about PAN and declaration', () => {
    expect(tcsHints(section, noPan)).toEqual(['No PAN: higher rate under s.397(2)']);
    expect(tcsHints(section, { ...withPan, tcs_declaration_received: true })).toEqual(['Declaration received: no TCS suggested']);
    expect(tcsHints(section, withPan)).toEqual([]);
    expect(tcsHints(section, null)).toEqual([]);
  });
});
