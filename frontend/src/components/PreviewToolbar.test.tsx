import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, test } from 'vitest';
import PreviewToolbar from './PreviewToolbar';

describe('PreviewToolbar title adornment', () => {
  test('renders a keyboard-accessible copy control beside the title', () => {
    const html = renderToStaticMarkup(
      <PreviewToolbar
        eyebrow="Invoice preview"
        title="Invoice INV-0007"
        titleId="invoice-preview-title"
        titleAdornment={<button type="button" title="Copy invoice number" aria-label="Copy invoice number">Copy</button>}
        primary={{ label: 'Share', icon: <span />, onClick: () => {} }}
        onClose={() => {}}
        closeLabel="Close invoice preview"
      />,
    );

    expect(html).toMatch(/preview-header__heading-row[\s\S]*<h2[^>]*>Invoice INV-0007<\/h2>[\s\S]*<button[^>]*aria-label="Copy invoice number"/);
  });

  test('keeps the existing heading markup without an adornment', () => {
    const html = renderToStaticMarkup(
      <PreviewToolbar
        eyebrow="Receipt preview"
        title="Receipt R-007"
        titleId="receipt-preview-title"
        primary={{ label: 'Share', icon: <span />, onClick: () => {} }}
        onClose={() => {}}
        closeLabel="Close receipt preview"
      />,
    );

    expect(html).toContain('<h2 id="receipt-preview-title" class="nav-panel__title">Receipt R-007</h2>');
    expect(html).not.toContain('preview-header__heading-row');
  });
});

describe('PreviewToolbar title with a document number', () => {
  const props = {
    eyebrow: 'Invoice preview',
    title: 'Purchase invoice PINV-2026-001',
    titleId: 'invoice-preview-title',
    titleNumber: 'PINV-2026-001',
    phoneNoun: 'Purchase',
    primary: { label: 'Share', icon: <span />, onClick: () => {} },
    onClose: () => {},
    closeLabel: 'Close invoice preview',
  };

  test('on a phone, splits the short noun from the number and keeps the full name', () => {
    const html = renderToStaticMarkup(<PreviewToolbar {...props} phone />);

    expect(html).toContain('aria-label="Purchase invoice PINV-2026-001"');
    expect(html).toMatch(
      /<span class="nav-panel__title-noun">Purchase<\/span> <span class="nav-panel__title-number">PINV-2026-001<\/span>/,
    );
  });

  test('on a phone without a short noun, uses the rest of the title as the noun', () => {
    const html = renderToStaticMarkup(
      <PreviewToolbar {...props} title="Invoice SI/2026-27/00123" titleNumber="SI/2026-27/00123" phoneNoun={undefined} phone />,
    );

    expect(html).toMatch(
      /<span class="nav-panel__title-noun">Invoice<\/span> <span class="nav-panel__title-number">SI\/2026-27\/00123<\/span>/,
    );
  });

  test('on desktop, keeps the full title as plain heading text', () => {
    const html = renderToStaticMarkup(<PreviewToolbar {...props} phone={false} />);

    expect(html).toMatch(/<h2 id="invoice-preview-title" class="nav-panel__title">Purchase invoice PINV-2026-001<\/h2>/);
    expect(html).not.toContain('nav-panel__title-number');
  });
});
