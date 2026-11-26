import { create } from 'zustand';
import type { Product } from '../types/api';

type StockLine = { product_id: number };
type StockProduct = Pick<Product, 'id' | 'maintain_inventory'>;

type InvoiceCancelState = {
  pendingCancelId: number | null;
  pendingCancelNumber: string | null;
  /* What the cancelled invoice billed, so the toast only says stock was put back when it was. */
  pendingCancelLines: StockLine[] | null;
  pendingCancelProducts: StockProduct[] | null;
  requestCancel: (
    invoiceId: number,
    invoiceNumber?: string | null,
    stock?: { lines: StockLine[]; products: StockProduct[] },
  ) => void;
  dismissCancel: () => void;
};

export const useInvoiceCancelStore = create<InvoiceCancelState>((set) => ({
  pendingCancelId: null,
  pendingCancelNumber: null,
  pendingCancelLines: null,
  pendingCancelProducts: null,
  requestCancel: (invoiceId, invoiceNumber, stock) =>
    set({
      pendingCancelId: invoiceId,
      pendingCancelNumber: invoiceNumber ?? null,
      pendingCancelLines: stock?.lines ?? null,
      pendingCancelProducts: stock?.products ?? null,
    }),
  dismissCancel: () =>
    set({ pendingCancelId: null, pendingCancelNumber: null, pendingCancelLines: null, pendingCancelProducts: null }),
}));
