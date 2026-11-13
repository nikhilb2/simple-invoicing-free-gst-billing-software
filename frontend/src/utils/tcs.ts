/**
 * TCS suggestions for the invoice form (#769), mirroring backend/src/services/tcs.py.
 * The app suggests a section rate; the user can always type the rate or amount.
 */
import type { Ledger, TaxWithholdingSection } from '../types/api';

/** Sl. No. 1 to 5 of s.394(1), all s.206C(1) under the 1961 Act: what a s.394(2) declaration covers. */
export const TCS_DECLARATION_LEGACY_CODES = ['206C(1)'];

const GSTIN_PATTERN = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/;

type TcsBuyer = Pick<Ledger, 'gst' | 'pan' | 'party_type' | 'tcs_declaration_received'>;

export function buyerHasPan(buyer: Partial<TcsBuyer> | null | undefined): boolean {
  if (!buyer) return false;
  if ((buyer.pan || '').trim()) return true;
  return GSTIN_PATTERN.test((buyer.gst || '').trim().toUpperCase());
}

export function declarationCovers(section: Pick<TaxWithholdingSection, 'legacy_code'>, buyer: Partial<TcsBuyer> | null | undefined): boolean {
  return Boolean(buyer?.tcs_declaration_received) && TCS_DECLARATION_LEGACY_CODES.includes(section.legacy_code || '');
}

/** The rate to offer: 0 under a declaration, the no-PAN rate without a PAN (capped at 20%), else the party's rate. */
export function suggestTcsRate(
  section: Pick<TaxWithholdingSection, 'legacy_code' | 'rate_individual_huf' | 'rate_other' | 'rate_no_pan'>,
  buyer: Partial<TcsBuyer> | null | undefined,
): number {
  if (declarationCovers(section, buyer)) return 0;
  let rate: number;
  if (!buyerHasPan(buyer)) rate = section.rate_no_pan;
  else if (buyer?.party_type === 'individual' || buyer?.party_type === 'huf') rate = section.rate_individual_huf;
  else rate = section.rate_other;
  return Math.min(rate, 20);
}

/** A rate as the server stores it: three places, half-up (NUMERIC(7,3)). */
export function roundTcsRate(value: number): number {
  const magnitude = Math.abs(value);
  const rounded = Math.round((magnitude + 4 * Number.EPSILON * Math.max(1, magnitude)) * 1000) / 1000;
  return rounded === 0 ? 0 : Math.sign(value) * rounded;
}

/** "TCS @ 2% (s.394(1) Sl. No. 4)", the line documents show. */
export function tcsLabel(rate: number | null | undefined, sectionRef: string | null | undefined): string {
  const pct = `${Number(rate ?? 0).toLocaleString('en-IN', { maximumFractionDigits: 3 })}%`;
  return sectionRef ? `TCS @ ${pct} (s.${sectionRef})` : `TCS @ ${pct}`;
}
