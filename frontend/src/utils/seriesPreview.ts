import type { InvoiceSeries, InvoiceSeriesUpdate } from '../types/api';

export function buildSeriesPreview(
  series: InvoiceSeriesUpdate,
  nextSequence: number,
  fyLabel?: string | null,
  now: Date = new Date(),
  fyStartYear?: number | null,
): string {
  const sep = series.separator ?? '-';
  const seq = String(nextSequence).padStart(series.pad_digits, '0');
  const prefix = series.prefix.trim().toUpperCase();
  const suffix = series.suffix.trim().toUpperCase();
  if (!series.include_year) {
    return `${prefix}${sep}${seq}${suffix}`;
  }
  // Real numbers take the document's date, which is normally today's local date.
  let yearPart: string;
  if (series.year_format === 'FY') {
    yearPart = fyLabel ?? 'FY';
  } else if (series.year_format === 'MM-YYYY') {
    yearPart = `${String(now.getMonth() + 1).padStart(2, '0')}${sep}${now.getFullYear()}`;
  } else {
    // Counters are per financial year, so the year is the one the FY starts in
    // (calendar year when there is no FY). MM-YYYY above keeps the calendar year.
    yearPart = `${fyStartYear ?? now.getFullYear()}`;
  }
  return `${prefix}${sep}${yearPart}${sep}${seq}${suffix}`;
}

export const MAX_NEXT_SEQUENCE = 999_999_999;

/** Keep editable empty text, but stop whole-number input at the API's limit. */
export function clampNextSequenceInput(raw: string): string {
  return /^\d+$/.test(raw.trim()) && Number(raw) > MAX_NEXT_SEQUENCE
    ? String(MAX_NEXT_SEQUENCE)
    : raw;
}

/**
 * The "Next number" box as typed: a whole number within the API range, or `null` while
 * it is blank or holds anything else. The box keeps the raw text, so clearing
 * it leaves it empty instead of snapping back to 1 (#922).
 */
export function parseNextSequenceInput(raw: string): number | null {
  const text = raw.trim();
  if (!/^\d+$/.test(text)) return null;
  const value = Number(text);
  return value >= 1 && value <= MAX_NEXT_SEQUENCE ? value : null;
}

/** Mirror the API's format-change check; counter-only edits remain allowed. */
export function gstr1SeriesFormatError(
  draft: InvoiceSeriesUpdate,
  saved: InvoiceSeries,
  savedGstin: string,
  fyLabel?: string | null,
  now: Date = new Date(),
  fyStartYear?: number | null,
): string | null {
  if (!savedGstin.trim() || !['sales', 'credit_note', 'delivery_challan'].includes(saved.voucher_type)) return null;
  const formatChanged = draft.prefix.trim().toUpperCase() !== saved.prefix
    || draft.suffix.trim().toUpperCase() !== saved.suffix
    || draft.include_year !== saved.include_year
    || draft.year_format !== saved.year_format
    || draft.separator !== saved.separator
    || draft.pad_digits !== saved.pad_digits;
  if (!formatChanged) return null;

  // The server reserves room for at least a four-digit counter, even when the
  // next number is shorter. Other financial years are still checked by the API.
  const longest = buildSeriesPreview(draft, Math.max(draft.next_sequence ?? 1, 9999), fyLabel, now, fyStartYear);
  if (longest.length > 16) return 'GSTR-1 numbers must be at most 16 characters.';
  if (!/^[A-Za-z0-9/-]+$/.test(longest)) return 'GSTR-1 numbers may only contain letters, digits, "-" and "/".';
  if (!/^[A-Za-z0-9]/.test(longest)) return 'GSTR-1 numbers must start with a letter or digit.';
  return null;
}
