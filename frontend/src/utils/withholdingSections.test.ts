import { describe, expect, it } from 'vitest';
import { sectionOptionLabel, sectionOptionLabels, sectionRefLabel } from './withholdingSections';

const row = (id: number, section_ref: string, nature: string, rate: number, effective_from = '2026-04-01') => ({
  id, section_ref, nature, rate_individual_huf: rate, rate_other: rate, effective_from,
});

describe('sectionRefLabel', () => {
  it('shows every reference with one "s." prefix', () => {
    expect(sectionRefLabel('393(1) Sl. No. 6(iii)')).toBe('s.393(1) Sl. No. 6(iii)');
    expect(sectionRefLabel('s.194J')).toBe('s.194J');
    expect(sectionRefLabel(null)).toBe('');
  });
});

describe('sectionOptionLabels', () => {
  it('tells apart the two natures under s.393(1) Sl. No. 6(iii)', () => {
    const labels = sectionOptionLabels([
      row(1, '393(1) Sl. No. 6(iii)', 'Fees for technical services, call centre or film royalty', 2),
      row(2, '393(1) Sl. No. 6(iii)', 'Professional fees and other specified sums', 10),
    ]);
    expect(labels.get(1)).toBe('s.393(1) Sl. No. 6(iii): Fees for technical services, call centre or film royalty (2%)');
    expect(labels.get(2)).toBe('s.393(1) Sl. No. 6(iii): Professional fees and other specified sums (10%)');
  });

  it('never repeats a label, even for rows that read the same', () => {
    const labels = sectionOptionLabels([
      row(1, '194C', 'Contractors', 1, '2025-04-01'),
      row(2, '194C', 'Contractors', 1, '2026-04-01'),
      row(3, '194C', 'Contractors', 1, '2026-04-01'),
    ]);
    expect(new Set(labels.values()).size).toBe(3);
    expect(labels.get(1)).toBe('s.194C: Contractors (1%), from 2025-04-01');
  });

  it('matches the single-option label when nothing clashes', () => {
    const only = row(5, '194C', 'Contractors', 1);
    expect(sectionOptionLabels([only]).get(5)).toBe(sectionOptionLabel(only));
  });
});
