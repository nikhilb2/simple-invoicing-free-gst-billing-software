import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import ProductQuickCreateModal from './ProductQuickCreateModal';

/* Server rendering reads a zustand store's initial state, where the dialog is
   closed, so the store is swapped for one that has it open. */
vi.mock('../../../store/useInvoiceComposerStore', () => {
  const state = {
    showProductCreateModal: true,
    closeProductCreateModal: () => {},
    setFeedbackError: () => {},
    setFeedbackSuccess: () => {},
    productCreateName: '',
    setCreatedProduct: () => {},
  };
  return {
    useInvoiceComposerStore: (selector: (current: typeof state) => unknown) => selector(state),
  };
});

/* No DOM here, so the open dialog is read back from server-rendered markup. */
function renderOpenModal(countsStockByDefault: boolean) {
  return renderToStaticMarkup(
    <QueryClientProvider client={new QueryClient()}>
      <ProductQuickCreateModal countsStockByDefault={countsStockByDefault} />
    </QueryClientProvider>,
  );
}

function stockBox(html: string): string {
  const match = html.match(/<input[^>]*id="modal-product-maintain-inventory"[^>]*>/);
  if (!match) throw new Error('no Maintain inventory box');
  return match[0];
}

describe('ProductQuickCreateModal stock counting (issue 983)', () => {
  it('starts a new company’s product without stock counting, so its first invoice is not refused', () => {
    const html = renderOpenModal(false);
    expect(stockBox(html)).not.toContain('checked');
    expect(html).not.toContain('id="modal-product-opening-stock"');
    expect(html).toContain('you can bill this item in any quantity');
  });

  it('keeps stock counting on, and asks for opening stock, where the company already counts stock', () => {
    const html = renderOpenModal(true);
    expect(stockBox(html)).toContain('checked');
    expect(html).toMatch(/<input[^>]*id="modal-product-opening-stock"[^>]*required/);
  });
});
