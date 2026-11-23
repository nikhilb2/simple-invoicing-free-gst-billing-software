import { describe, expect, it } from 'vitest';
import { renderToString } from 'react-dom/server';
import LedgerCombobox from './LedgerCombobox';

const noop = () => undefined;

describe('LedgerCombobox with no ledgers', () => {
  it('is disabled by default, as the other pickers expect', () => {
    const html = renderToString(<LedgerCombobox id="x" ledgers={[]} value="" onChange={noop} required />);
    expect(html).toContain('disabled=""');
    expect(html).toContain('No ledgers available');
  });

  it('stays enabled when asked, so the required check can stop the form', () => {
    const html = renderToString(
      <LedgerCombobox id="x" ledgers={[]} value="" onChange={noop} required keepEnabledWhenEmpty emptyPlaceholder="No customers yet" />,
    );
    expect(html).not.toContain('disabled=""');
    expect(html).toContain('placeholder="No customers yet"');
    expect(html).toContain('data-focus-on-error="true"');
  });
});
