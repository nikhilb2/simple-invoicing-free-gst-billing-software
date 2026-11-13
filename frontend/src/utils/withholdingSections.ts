import type { TaxWithholdingSection } from '../types/api';

type SectionLabelInput = Pick<TaxWithholdingSection, 'section_ref' | 'nature'> & {
  rate_individual_huf: number | null;
  rate_other: number | null;
};

/** "s.393(1) Sl. No. 6(iii)": the one way a TDS/TCS section reference is shown. */
export function sectionRefLabel(sectionRef: string | null | undefined): string {
  const ref = (sectionRef || '').trim();
  if (!ref) return '';
  return ref.startsWith('s.') ? ref : `s.${ref}`;
}

function rateText(section: SectionLabelInput): string {
  const rates = [section.rate_individual_huf, section.rate_other].filter((r): r is number => typeof r === 'number');
  if (rates.length === 0) return '';
  return rates.length === 1 || rates[0] === rates[1] ? ` (${rates[0]}%)` : ` (${rates[0]}% / ${rates[1]}%)`;
}

/**
 * A TDS or TCS section as a dropdown option, e.g.
 * "s.393(1) Sl. No. 6(iii): Professional fees and other specified sums (10%)".
 * One serial number can cover several natures at different rates, so the
 * reference alone is not enough to tell options apart.
 */
export function sectionOptionLabel(section: SectionLabelInput): string {
  return `${sectionRefLabel(section.section_ref)}: ${section.nature}${rateText(section)}`;
}

/**
 * Labels for a whole dropdown, keyed by section id, guaranteed unique: should two
 * rows still read the same, each gets its effective-from date (then its id).
 */
export function sectionOptionLabels(
  sections: Array<SectionLabelInput & Pick<TaxWithholdingSection, 'id'> & Partial<Pick<TaxWithholdingSection, 'effective_from'>>>,
): Map<number, string> {
  const base = sections.map((section) => sectionOptionLabel(section));
  const counts = new Map<string, number>();
  base.forEach((label) => counts.set(label, (counts.get(label) ?? 0) + 1));
  const labels = new Map<number, string>();
  const used = new Set<string>();
  sections.forEach((section, index) => {
    let label = base[index];
    if ((counts.get(label) ?? 0) > 1 && section.effective_from) label = `${label}, from ${section.effective_from}`;
    if (used.has(label)) label = `${label} [#${section.id}]`;
    used.add(label);
    labels.set(section.id, label);
  });
  return labels;
}
