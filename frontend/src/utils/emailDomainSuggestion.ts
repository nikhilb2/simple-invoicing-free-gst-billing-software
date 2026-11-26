// Suggests a fix for a mistyped email domain ("someone@gmaui.com" ->
// "someone@gmail.com"). It only ever produces a hint: the caller must not
// block submit or add validation errors because of it.

const COMMON_DOMAINS = [
  'gmail.com',
  'yahoo.com',
  'outlook.com',
  'hotmail.com',
  'yahoo.co.in',
  'rediffmail.com',
];

// Real providers that sit within a couple of edits of a common domain (ymail.com
// is one letter from gmail.com). They must never be "corrected".
const OTHER_REAL_DOMAINS = new Set([
  'ymail.com',
  'gmx.com',
  'gmx.net',
  'live.com',
  'live.in',
  'msn.com',
  'aol.com',
  'icloud.com',
  'me.com',
  'mac.com',
  'proton.me',
  'protonmail.com',
  'zoho.com',
  'rediff.com',
  'yahoo.in',
  'yahoo.co.uk',
  'yahoo.fr',
  'yahoo.de',
  'yahoo.ca',
  'yahoo.it',
  'yahoo.es',
  'outlook.in',
  'hotmail.in',
  'hotmail.co.uk',
  'hotmail.fr',
  'hotmail.de',
  'hotmail.it',
  'hotmail.es',
]);

// Two edits on a short domain match too many real ones, so only domains this
// long get the wider allowance.
const MIN_LENGTH_FOR_TWO_EDITS = 8;

export function levenshtein(a: string, b: string): number {
  if (a === b) return 0;
  let prev = Array.from({ length: b.length + 1 }, (_, j) => j);
  for (let i = 1; i <= a.length; i += 1) {
    const row = [i];
    for (let j = 1; j <= b.length; j += 1) {
      row[j] = Math.min(
        prev[j] + 1,
        row[j - 1] + 1,
        prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1),
      );
    }
    prev = row;
  }
  return prev[b.length];
}

/**
 * The corrected address, or null when there is nothing to suggest: no domain
 * yet, an exact or known domain, no close match, or two equally close matches.
 * The local part is kept exactly as typed.
 */
export function suggestEmailDomain(email: string): string | null {
  const value = email.trim();
  const at = value.lastIndexOf('@');
  if (at < 1) return null;
  const local = value.slice(0, at);
  const domain = value.slice(at + 1).toLowerCase();
  // Only a domain that looks finished: a dot and a TLD of at least two letters.
  if (!/^[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}$/.test(domain)) return null;
  if (COMMON_DOMAINS.includes(domain) || OTHER_REAL_DOMAINS.has(domain)) return null;

  const maxEdits = domain.length >= MIN_LENGTH_FOR_TWO_EDITS ? 2 : 1;
  let best: string | null = null;
  let bestDistance = Infinity;
  let tied = false;
  for (const candidate of COMMON_DOMAINS) {
    const distance = levenshtein(domain, candidate);
    if (distance > maxEdits) continue;
    if (distance < bestDistance) {
      best = candidate;
      bestDistance = distance;
      tied = false;
    } else if (distance === bestDistance) {
      tied = true;
    }
  }
  if (!best || tied) return null;
  return `${local}@${best}`;
}
