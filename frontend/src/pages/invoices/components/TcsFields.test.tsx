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
    expect(html).toContain('394(1) Sl. No. 4 - Sale of scrap');
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
});
