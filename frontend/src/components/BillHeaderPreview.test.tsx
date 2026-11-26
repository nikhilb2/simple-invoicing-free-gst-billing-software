import { readFileSync } from 'node:fs';
import { renderToString } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import BillHeaderPreview, { BILL_HEADER_NUMBER, BILL_HEADER_TITLE } from './BillHeaderPreview';

const css = readFileSync(new URL('../styles.css', import.meta.url), 'utf8');

/** The declarations of one top-level rule, e.g. `.bill-header-preview__name`. */
function rule(selector: string): string {
  const match = css.match(new RegExp(`(^|\\n)${selector.replace(/[.]/g, '\\.')} \\{([^}]*)\\}`));
  return match?.[2] ?? '';
}

describe('BillHeaderPreview', () => {
  it('shows the typed business name', () => {
    const html = renderToString(<BillHeaderPreview name="  Ravi Kumar Mobiles " />);
    expect(html).toContain('Ravi Kumar Mobiles');
    expect(html).not.toContain('Your business name');
    expect(html).not.toContain('bill-header-preview__name--empty');
  });

  it('falls back to a placeholder for an empty or blank name', () => {
    for (const name of ['', '   ']) {
      const html = renderToString(<BillHeaderPreview name={name} />);
      expect(html).toContain('Your business name');
      expect(html).toContain('bill-header-preview__name--empty');
    }
  });

  it('is hidden from assistive tech', () => {
    expect(renderToString(<BillHeaderPreview name="A" />)).toContain('aria-hidden="true"');
  });

  it('shows "TAX INVOICE · Bill 1" after the name, with "· Bill 1" in its own span', () => {
    const html = renderToString(<BillHeaderPreview name="Ravi Kumar" />);
    expect(BILL_HEADER_TITLE + BILL_HEADER_NUMBER).toBe('TAX INVOICE · Bill 1');
    expect(html).toContain(
      `<span class="field-hint bill-header-preview__meta">${BILL_HEADER_TITLE}<span class="bill-header-preview__number">${BILL_HEADER_NUMBER}</span></span>`,
    );
    expect(html.indexOf('Ravi Kumar')).toBeLessThan(html.indexOf('TAX INVOICE'));
  });

  it('keeps the meta next to the name at every width (styles)', () => {
    const name = rule('.bill-header-preview__name');
    // Shrinks for a long name (ellipsis) but never grows, so the meta is not pushed to the far edge.
    expect(name).toMatch(/flex:\s*0 1 auto/);
    expect(name).toMatch(/text-overflow:\s*ellipsis/);
    expect(name).toMatch(/min-width:\s*0/);
    expect(rule('.bill-header-preview')).toMatch(/gap:\s*12px/);
    expect(rule('.bill-header-preview__meta')).toMatch(/flex:\s*0 0 auto/);
    // Only the bill number hides, and only under 420px (Naina's must on #1114).
    expect(css).toMatch(
      /@media \(max-width: 419\.98px\) \{\s*\.bill-header-preview__number \{\s*display: none;\s*\}\s*\}/,
    );
    for (const selector of ['.bill-header-preview', '.bill-header-preview__name', '.bill-header-preview__meta']) {
      expect(rule(selector)).not.toMatch(/display:\s*none/);
    }
  });
});
