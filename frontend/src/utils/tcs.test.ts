import { describe, expect, it } from 'vitest';
import { buyerHasPan, suggestTcsRate, tcsLabel } from './tcs';

const scrap2025 = { legacy_code: '206C(1)', rate_individual_huf: 2, rate_other: 2, rate_no_pan: 5 };
const vehicle = { legacy_code: '206C(1F)', rate_individual_huf: 1, rate_other: 1, rate_no_pan: 5 };

describe('TCS suggestions', () => {
  it('reads a PAN from the PAN field or the GSTIN', () => {
    expect(buyerHasPan({ pan: 'ABCDE1234F', gst: '' })).toBe(true);
    expect(buyerHasPan({ pan: null, gst: '29ABCDE1234F1ZW' })).toBe(true);
    expect(buyerHasPan({ pan: null, gst: '' })).toBe(false);
  });

  it('suggests the section rate, the no-PAN rate, or nothing under a declaration', () => {
    expect(suggestTcsRate(scrap2025, { gst: '29ABCDE1234F1ZW', pan: null })).toBe(2);
    expect(suggestTcsRate(scrap2025, { gst: '', pan: null })).toBe(5);
    expect(suggestTcsRate(scrap2025, { gst: '29ABCDE1234F1ZW', pan: null, tcs_declaration_received: true })).toBe(0);
    // A declaration covers Sl. No. 1 to 5 only, not motor vehicles.
    expect(suggestTcsRate(vehicle, { pan: 'ABCDE1234F', gst: '', tcs_declaration_received: true })).toBe(1);
  });

  it('caps a no-PAN rate at 20%', () => {
    expect(suggestTcsRate({ ...scrap2025, rate_no_pan: 25 }, { gst: '', pan: null })).toBe(20);
  });

  it('labels the document line', () => {
    expect(tcsLabel(2, '394(1) Sl. No. 4')).toBe('TCS @ 2% (s.394(1) Sl. No. 4)');
  });
});
