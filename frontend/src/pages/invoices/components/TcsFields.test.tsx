import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import TcsFields from './TcsFields';
import type { TaxWithholdingSection } from '../../../types/api';

const scrap: TaxWithholdingSection = {
  id: 7, kind: 'tcs', act: 2025, section_ref: '394(1) Sl. No. 4', legacy_code: '206C(1)', nature: 'Sale of scrap',
  rate_individual_huf: 2, rate_other: 2, rate_no_pan: 5, threshold_single: null, threshold_aggregate: null,
  threshold_note: null, base: 'gross', effective_from: '2026-04-01', effective_to: null,
};

describe('TcsFields (quick invoice modal)', () => {
  it('offers no section until the user picks one', () => {
    const html = renderToStaticMarkup(
      <TcsFields idPrefix="m" form={{ sectionId: '', rateText: null, amountText: null }} onChange={() => {}}
        sections={[scrap]} section={null} buyer={{ gst: '29ABCDE1234F1ZW', pan: null }} previewAmount={undefined} currencyCode="INR" />,
    );
    expect(html).toContain('No TCS');
    expect(html).toContain('s.394(1) Sl. No. 4: Sale of scrap (2%)');
    expect(html).not.toContain('Rate %');
  });

  it('shows the suggested rate and the worked-out amount for the scrap example', () => {
    const html = renderToStaticMarkup(
      <TcsFields idPrefix="m" form={{ sectionId: '7', rateText: null, amountText: null }} onChange={() => {}}
        sections={[scrap]} section={scrap} buyer={{ gst: '29ABCDE1234F1ZW', pan: null }} previewAmount={2360} currencyCode="INR" />,
    );
    expect(html).toContain('value="2"');
    expect(html).toContain('value="2360"');
    expect(html).toContain('TCS @ 2% (s.394(1) Sl. No. 4)');
  });

  it('shows the document total beside the TCS line when the composer passes it', () => {
    const html = renderToStaticMarkup(
      <TcsFields idPrefix="invoice" form={{ sectionId: '7', rateText: null, amountText: null }} onChange={() => {}}
        sections={[scrap]} section={scrap} buyer={{ gst: '29ABCDE1234F1ZW', pan: null }} previewAmount={2360}
        currencyCode="INR" totalAmount={120360} />,
    );
    expect(html).toContain('id="invoice-tcs-section"');
    expect(html).toContain('Total:');
    expect(html).toMatch(/1,20,360/);
  });

  it('tells apart two natures under one serial number', () => {
    const lrsEducation = { ...scrap, id: 8, section_ref: '394(1) Sl. No. 7', nature: 'LRS remittance for education or medical purposes' };
    const lrsOther = { ...scrap, id: 9, section_ref: '394(1) Sl. No. 7', nature: 'Other LRS remittances', rate_individual_huf: 20, rate_other: 20 };
    const html = renderToStaticMarkup(
      <TcsFields idPrefix="m" form={{ sectionId: '', rateText: null, amountText: null }} onChange={() => {}}
        sections={[lrsEducation, lrsOther]} section={null} buyer={null} previewAmount={undefined} currencyCode="INR" />,
    );
    expect(html).toContain('s.394(1) Sl. No. 7: LRS remittance for education or medical purposes (2%)');
    expect(html).toContain('s.394(1) Sl. No. 7: Other LRS remittances (20%)');
  });
});
