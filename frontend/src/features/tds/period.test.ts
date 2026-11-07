import { describe, expect, it } from 'vitest';
import {
  certificateForm,
  currentTaxYear,
  quarterLabel,
  quarterOptions,
  taxYearLabel,
  taxYearOptions,
} from './period';

describe('currentTaxYear', () => {
  it.each([
    [new Date(2026, 3, 1), 2026],
    [new Date(2026, 10, 8), 2026],
    [new Date(2027, 2, 31), 2026],
    [new Date(2027, 0, 1), 2026],
    [new Date(2026, 2, 31), 2025],
  ])('maps %s to %s', (date, expected) => {
    expect(currentTaxYear(date)).toBe(expected);
  });
});

describe('taxYearLabel', () => {
  it.each([
    [2026, '2026-27'],
    [2025, '2025-26'],
    [2099, '2099-00'],
    [2009, '2009-10'],
  ])('labels %s as %s', (year, label) => {
    expect(taxYearLabel(year)).toBe(label);
  });
});

describe('taxYearOptions', () => {
  it('lists the current year and three before it, newest first', () => {
    expect(taxYearOptions(new Date(2026, 10, 8))).toEqual([
      { value: 2026, label: '2026-27' },
      { value: 2025, label: '2025-26' },
      { value: 2024, label: '2024-25' },
      { value: 2023, label: '2023-24' },
    ]);
  });

  it('starts one year earlier before 1 April', () => {
    expect(taxYearOptions(new Date(2027, 2, 31), 1)).toEqual([
      { value: 2026, label: '2026-27' },
      { value: 2025, label: '2025-26' },
    ]);
  });
});

describe('quarter labels', () => {
  it('names each quarter', () => {
    expect([1, 2, 3, 4].map(quarterLabel)).toEqual([
      'Q1 (Apr–Jun)',
      'Q2 (Jul–Sep)',
      'Q3 (Oct–Dec)',
      'Q4 (Jan–Mar)',
    ]);
  });

  it('names the whole year', () => {
    expect(quarterLabel(null)).toBe('All quarters');
  });

  it('offers all quarters first, then Q1 to Q4', () => {
    expect(quarterOptions().map((o) => o.value)).toEqual([null, 1, 2, 3, 4]);
  });
});

describe('certificateForm', () => {
  it.each([
    ['2026-03-31', 'Form 16A'],
    ['2025-04-01', 'Form 16A'],
    ['2026-04-01', 'Form 131'],
    ['2026-11-08', 'Form 131'],
    ['2026-03-31T10:00:00', 'Form 16A'],
  ])('uses the right form for %s', (date, form) => {
    expect(certificateForm(date)).toBe(form);
  });
});
