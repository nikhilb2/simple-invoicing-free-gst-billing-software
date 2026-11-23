import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import LedgerQuickCreateModal from './LedgerQuickCreateModal';

/* Server rendering reads a zustand store's initial state, where the dialog is
   closed, so the store is swapped for one that has it open. */
vi.mock('../../../store/useInvoiceComposerStore', () => {
  const state = {
    showLedgerCreateModal: true,
    closeLedgerCreateModal: () => {},
    setSelectedLedgerId: () => {},
    setFeedbackError: () => {},
    setFeedbackSuccess: () => {},
  };
  return {
    useInvoiceComposerStore: (selector: (current: typeof state) => unknown) => selector(state),
  };
});

/* No DOM here, so the open dialog is read back from server-rendered markup. */
function renderOpenModal() {
  return renderToStaticMarkup(
    <QueryClientProvider client={new QueryClient()}>
      <LedgerQuickCreateModal />
    </QueryClientProvider>,
  );
}

function tagFor(html: string, id: string): string {
  const match = html.match(new RegExp(`<(input|textarea)[^>]*id="${id}"[^>]*>`));
  if (!match) throw new Error(`no field ${id}`);
  return match[0];
}

describe('LedgerQuickCreateModal (issue 955)', () => {
  it('lets a spaced GSTIN reach normalization without browser truncation', () => {
    const input = tagFor(renderOpenModal(), 'modal-ledger-gst');
    expect(input.toLowerCase()).not.toContain('maxlength');
    expect(input).toContain('pattern=');
  });

  it('requires only the customer name', () => {
    const html = renderOpenModal();
    expect(tagFor(html, 'modal-ledger-name')).toContain('required');
    expect(tagFor(html, 'modal-ledger-phone')).not.toContain('required');
    expect(tagFor(html, 'modal-ledger-address')).not.toContain('required');
  });

  it('does not mark phone or address with the required star', () => {
    const html = renderOpenModal();
    expect(html).toContain('>Name *</label>');
    expect(html).toContain('>Phone number</label>');
    expect(html).toContain('>Address</label>');
  });
});
