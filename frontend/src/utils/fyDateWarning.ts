import type { FinancialYear } from '../api/financialYears';

function fyName(label: string): string {
  return label.trim().toUpperCase().startsWith('FY') ? label : `FY ${label}`;
}

/** The April-to-March year a date falls in, e.g. "2027-28" for 2027-04-01. Same rule as the API. */
export function indianFyLabel(isoDate: string): string {
  const year = Number(isoDate.slice(0, 4));
  const month = Number(isoDate.slice(5, 7));
  const startYear = month >= 4 ? year : year - 1;
  return `${startYear}-${String(startYear + 1).slice(-2)}`;
}

/**
 * The warning to show under a date field before saving, or null for none.
 * - the company has no financial years: nothing (documents are numbered without a year);
 * - no year contains the date: the API will refuse it, so say so (same text as the API);
 * - another year contains the date but it is not the active one: `outsideActiveText`.
 */
export function fyDateWarning(
  date: string,
  fyList: FinancialYear[],
  activeFY: FinancialYear | null,
  outsideActiveText: (activeLabel: string) => string,
): string | null {
  const day = date.slice(0, 10);
  if (day === '' || fyList.length === 0) return null;
  if (!fyList.some((fy) => day >= fy.start_date && day <= fy.end_date)) {
    const latest = [...fyList].sort((a, b) => b.start_date.localeCompare(a.start_date))[0];
    const suggested = activeFY ?? fyList.find((fy) => fy.is_active) ?? latest;
    return (
      `This date is in ${fyName(indianFyLabel(day))}, which isn't set up yet. ` +
      `An admin can add it from the side menu (Financial Year → + New FY). ` +
      `Or pick a date in ${fyName(suggested.label)}.`
    );
  }
  if (activeFY !== null && (day < activeFY.start_date || day > activeFY.end_date)) {
    return outsideActiveText(activeFY.label);
  }
  return null;
}
