import type { ShareLink } from '../../types/api';
import { formatDate } from '../../utils/formatting';

/** "2 hours ago" for the last-opened line. Intl does the pluralising. */
export function formatRelativeTime(iso: string): string {
  // The API records last_viewed_at in UTC but can omit the timezone suffix.
  const withoutOffset = /T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?$/i.test(iso);
  const then = new Date(withoutOffset ? `${iso}Z` : iso).getTime();
  if (Number.isNaN(then)) {
    return 'recently';
  }

  const seconds = Math.round((then - Date.now()) / 1000);
  const units: [Intl.RelativeTimeFormatUnit, number][] = [
    ['second', 60],
    ['minute', 60],
    ['hour', 24],
    ['day', 30],
    ['month', 12],
    ['year', Number.POSITIVE_INFINITY],
  ];

  const formatter = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' });
  let value = seconds;
  for (const [unit, step] of units) {
    if (Math.abs(value) < step) {
      return formatter.format(Math.round(value), unit);
    }
    value /= step;
  }
  return formatter.format(Math.round(value), 'year');
}

export function describeViews(viewCount: number, lastViewedAt: string | null): string {
  if (viewCount <= 0) {
    return 'Not opened yet';
  }

  const opened = viewCount === 1 ? 'Opened once' : `Opened ${viewCount} times`;
  return lastViewedAt ? `${opened} · last ${formatRelativeTime(lastViewedAt)}` : opened;
}

/**
 * The period a statement link covers, as a row label. A link with no dates
 * is the open-ended one payment reminders reuse: it always shows the
 * ledger's current statement, so it has no fixed period to print.
 * Dates print as DD-MM-YYYY; the link keeps its ISO values for the API.
 */
export function describeShareLinkPeriod(link: ShareLink): string {
  if (!link.from_date && !link.to_date) {
    return 'Always current (payment reminders)';
  }
  if (link.from_date && link.to_date) {
    return `${formatDate(link.from_date)} to ${formatDate(link.to_date)}`;
  }
  if (link.from_date) {
    return `From ${formatDate(link.from_date)}`;
  }
  return `Until ${formatDate(link.to_date)}`;
}
