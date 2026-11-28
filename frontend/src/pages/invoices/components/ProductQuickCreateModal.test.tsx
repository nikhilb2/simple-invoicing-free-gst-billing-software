import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import ProductQuickCreateModal, { SerialTrackingHint } from './ProductQuickCreateModal';

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
    expect(html).toContain('Starts off because this company does not count stock yet.');
  });

  it('keeps stock counting on, and asks for opening stock, where the company already counts stock', () => {
    const html = renderOpenModal(true);
    expect(stockBox(html)).toContain('checked');
    expect(html).toContain('Starts on because this company already counts stock.');
    expect(html).toMatch(/<input[^>]*id="modal-product-opening-stock"[^>]*required/);
  });
});

describe('serial tracking warning', () => {
  it('warns that billing needs serials in stock when tracking is checked', () => {
    const html = renderToStaticMarkup(<SerialTrackingHint tracked />);
    expect(html).toContain('class="field-warning" role="status"');
    expect(html).toContain('You can&#x27;t bill this product until you add its serial numbers (on a purchase entry, or with Update stock). Leave this off to bill it now.');
    expect(html).not.toContain('Receive the units on a purchase entry once the product is saved.');
  });

  it('keeps only the original hint when tracking is unchecked', () => {
    const html = renderToStaticMarkup(<SerialTrackingHint tracked={false} />);
    expect(html).not.toContain('role="status"');
    expect(html).toContain('Receive the units on a purchase entry once the product is saved.');
    expect(renderOpenModal(false)).not.toContain('Leave this off to bill it now.');
  });
});

describe('ProductQuickCreateModal field errors (issue 1153)', () => {
  it('turns the browser bubble off, so our own messages run', () => {
    expect(renderOpenModal(true)).toMatch(/<form[^>]*novalidate=""/);
  });

  it('shows no field message before Save was tapped', () => {
    expect(renderOpenModal(true)).not.toContain('field-error');
  });
});
