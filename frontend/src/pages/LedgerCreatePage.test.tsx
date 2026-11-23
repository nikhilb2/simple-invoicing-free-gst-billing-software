import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import LedgerCreatePage from './LedgerCreatePage';

/* No DOM here, so the form is read back from server-rendered markup. */
function render() {
  return renderToStaticMarkup(
    <MemoryRouter initialEntries={['/ledgers/new']}>
      <LedgerCreatePage />
    </MemoryRouter>,
  );
}

function tagFor(html: string, id: string): string {
  const match = html.match(new RegExp(`<(input|textarea)[^>]*id="${id}"[^>]*>`));
  if (!match) throw new Error(`no field ${id}`);
  return match[0];
}

describe('LedgerCreatePage (issue 955)', () => {
  it('requires only the ledger name', () => {
    const html = render();
    expect(tagFor(html, 'ledger-name')).toContain('required');
    expect(tagFor(html, 'ledger-phone')).not.toContain('required');
    expect(tagFor(html, 'ledger-address')).not.toContain('required');
    expect(html).toContain('<strong>* Required:</strong> ledger name.');
  });
});
