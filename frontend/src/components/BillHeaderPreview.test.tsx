import { readFileSync } from 'node:fs';
import { renderToString } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import BillHeaderPreview, { BILL_HEADER_META } from './BillHeaderPreview';

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

  it('shows "TAX INVOICE · Bill 1" in full, as one piece, after the name', () => {
    const html = renderToString(<BillHeaderPreview name="Ravi Kumar" />);
    expect(BILL_HEADER_META).toBe('TAX INVOICE · Bill 1');
    expect(html).toContain(`<span class="field-hint bill-header-preview__meta">${BILL_HEADER_META}</span>`);
    expect(html.indexOf('Ravi Kumar')).toBeLessThan(html.indexOf('TAX INVOICE'));
    // Nothing a phone-width rule could hide on its own.
    expect(html).not.toContain('bill-header-preview__number');
  });

  it('keeps the meta next to the name at every width (styles)', () => {
    const name = rule('.bill-header-preview__name');
    // Shrinks for a long name (ellipsis) but never grows, so the meta is not pushed to the far edge.
    expect(name).toMatch(/flex:\s*0 1 auto/);
    expect(name).toMatch(/text-overflow:\s*ellipsis/);
    expect(name).toMatch(/min-width:\s*0/);
    expect(rule('.bill-header-preview')).toMatch(/gap:\s*12px/);
    expect(rule('.bill-header-preview__meta')).toMatch(/flex:\s*0 0 auto/);
    // The unapproved "hide · Bill 1 under 420px" rule is gone.
    expect(css).not.toMatch(/bill-header-preview[^{]*\{[^}]*display:\s*none/);
  });
});
