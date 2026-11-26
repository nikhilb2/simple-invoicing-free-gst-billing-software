import { renderToString } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import BillHeaderPreview from './BillHeaderPreview';

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

  it('shows the bill title and number', () => {
    const html = renderToString(<BillHeaderPreview name="A" />);
    expect(html).toContain('TAX INVOICE');
    expect(html).toContain('bill-header-preview__number');
    expect(html).toContain(' · Bill 1');
  });
});
