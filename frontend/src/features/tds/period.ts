/** Pure helpers for the TDS report's tax year and quarter pickers. */

/** First deduction date governed by the Income-tax Act, 2025. */
export const NEW_ACT_START = '2026-04-01';

/** A tax year starts on 1 April; the start year names it. */
export function currentTaxYear(date: Date = new Date()): number {
  return date.getMonth() >= 3 ? date.getFullYear() : date.getFullYear() - 1;
}

/** 2026 => "2026-27". */
export function taxYearLabel(taxYear: number): string {
  return `${taxYear}-${String((taxYear + 1) % 100).padStart(2, '0')}`;
}

/** The current tax year and the `back` before it, newest first. */
export function taxYearOptions(
  date: Date = new Date(),
  back = 3,
): { value: number; label: string }[] {
  const current = currentTaxYear(date);
  return Array.from({ length: back + 1 }, (_, i) => ({
    value: current - i,
    label: taxYearLabel(current - i),
  }));
}

export const QUARTER_LABELS: Record<number, string> = {
  1: 'Q1 (Apr–Jun)',
  2: 'Q2 (Jul–Sep)',
  3: 'Q3 (Oct–Dec)',
  4: 'Q4 (Jan–Mar)',
};

export function quarterLabel(quarter: number | null): string {
  return quarter === null ? 'All quarters' : (QUARTER_LABELS[quarter] ?? `Q${quarter}`);
}

export function quarterOptions(): { value: number | null; label: string }[] {
  return [null, 1, 2, 3, 4].map((value) => ({ value, label: quarterLabel(value) }));
}

/** Certificate a customer issues for a deduction made on this date (YYYY-MM-DD). */
export function certificateForm(deductionDate: string): 'Form 16A' | 'Form 131' {
  return deductionDate.slice(0, 10) < NEW_ACT_START ? 'Form 16A' : 'Form 131';
}
