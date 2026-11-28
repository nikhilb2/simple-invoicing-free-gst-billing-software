import { describe, expect, it } from 'vitest';
import type { FinancialYear } from '../api/financialYears';
import { fyDateWarning, indianFyLabel } from './fyDateWarning';

const fy = (label: string, start: string, end: string, active = false): FinancialYear => ({
  id: 1, label, start_date: start, end_date: end, is_active: active,
});
const fy2627 = fy('2026-27', '2026-04-01', '2027-03-31', true);
const fy2526 = fy('2025-26', '2025-04-01', '2026-03-31');
const still = (label: string) => `outside ${label}, still created`;

describe('indianFyLabel', () => {
  it('uses the April-to-March year of the date', () => {
    expect(indianFyLabel('2027-04-01')).toBe('2027-28');
    expect(indianFyLabel('2027-03-31')).toBe('2026-27');
    expect(indianFyLabel('2099-12-31')).toBe('2099-00');
  });
});

describe('fyDateWarning', () => {
  it('shows the refusal text when no year holds the date', () => {
    expect(fyDateWarning('2027-04-01', [fy2627], fy2627, still)).toBe(
      "This date is in FY 2027-28, which isn't set up yet. An admin can add it from the side menu (Financial Year → + New FY). Or pick a date in FY 2026-27.",
    );
  });

  it('names the date\'s own year, and the latest year when none is active', () => {
    const inactive = { ...fy2627, is_active: false };
    const text = fyDateWarning('2024-02-10', [fy2526, inactive], null, still);
    expect(text).toContain('This date is in FY 2023-24,');
    expect(text).toContain('Or pick a date in FY 2026-27.');
  });

  it('keeps a label that already says FY', () => {
    const named = fy('FY 2026-27', '2026-04-01', '2027-03-31', true);
    expect(fyDateWarning('2028-05-01', [named], named, still)).toContain('pick a date in FY 2026-27.');
  });

  it('keeps the "will still be created" text when another year holds the date', () => {
    expect(fyDateWarning('2026-03-31', [fy2627, fy2526], fy2627, still)).toBe('outside 2026-27, still created');
  });

  it('says nothing inside the active year, with an empty date, or with no years', () => {
    expect(fyDateWarning('2026-10-01', [fy2627], fy2627, still)).toBeNull();
    expect(fyDateWarning('', [fy2627], fy2627, still)).toBeNull();
    expect(fyDateWarning('2027-04-01', [], null, still)).toBeNull();
  });

  it('accepts a full timestamp', () => {
    expect(fyDateWarning('2027-04-01T00:00:00', [fy2627], fy2627, still)).toContain('FY 2027-28');
  });
});
