import { create } from 'zustand';
import { captureEvent } from '../lib/analytics';
import type { StockShortage } from '../features/invoices/stockShortage';
import type { Product } from '../types/api';

/** Where the Update stock dialog starts when it is opened from a stock error. */
export type StockUpdateStart = { productId: number; quantity: number };

type InvoiceComposerStore = {
  stockUpdateStart: StockUpdateStart | null;
  /** The product the last save ran short of, until stock is added or the form is cleared. */
  stockShortage: StockShortage | null;
  setStockShortage: (stockShortage: StockShortage | null) => void;
  selectedLedgerId: string;
  showLedgerCreateModal: boolean;
  showProductCreateModal: boolean;
  /** Name to prefill in the quick-add form, from text typed into a line's product box. */
  productCreateName: string;
  /** The line that asked for the new product, so it lands there. Null for the page buttons. */
  productCreateLineId: number | null;
  /** A product just saved from the quick-add form, waiting for the composer to put it on a line. */
  createdProduct: Product | null;
  setCreatedProduct: (product: Product | null) => void;
  showStockUpdateModal: boolean;
  feedbackError: string;
  feedbackSuccess: string;
  setSelectedLedgerId: (selectedLedgerId: string) => void;
  openLedgerCreateModal: () => void;
  closeLedgerCreateModal: () => void;
  openProductCreateModal: () => void;
  openProductCreateFromLine: (name: string, lineId: number) => void;
  closeProductCreateModal: () => void;
  openStockUpdateModal: (start?: StockUpdateStart) => void;
  closeStockUpdateModal: () => void;
  setFeedbackError: (feedbackError: string) => void;
  setFeedbackSuccess: (feedbackSuccess: string) => void;
  clearFeedback: () => void;
  clearFeedbackError: () => void;
  clearFeedbackSuccess: () => void;
};

export const useInvoiceComposerStore = create<InvoiceComposerStore>((set, get) => ({
  selectedLedgerId: '',
  showLedgerCreateModal: false,
  showProductCreateModal: false,
  productCreateName: '',
  productCreateLineId: null,
  createdProduct: null,
  setCreatedProduct: (createdProduct) => set({ createdProduct }),
  showStockUpdateModal: false,
  stockUpdateStart: null,
  stockShortage: null,
  setStockShortage: (stockShortage) => set({ stockShortage }),
  feedbackError: '',
  feedbackSuccess: '',
  setSelectedLedgerId: (selectedLedgerId) => set({ selectedLedgerId }),
  openLedgerCreateModal: () => {
    if (get().showLedgerCreateModal) return;
    set({ showLedgerCreateModal: true });
    captureEvent('ledger_quick_create_opened');
  },
  closeLedgerCreateModal: () => set({ showLedgerCreateModal: false }),
  openProductCreateModal: () => set({ showProductCreateModal: true, productCreateName: '', productCreateLineId: null }),
  openProductCreateFromLine: (name, lineId) => set({ showProductCreateModal: true, productCreateName: name, productCreateLineId: lineId }),
  closeProductCreateModal: () => set({ showProductCreateModal: false }),
  openStockUpdateModal: (start) => set({ showStockUpdateModal: true, stockUpdateStart: start ?? null }),
  closeStockUpdateModal: () => set({ showStockUpdateModal: false, stockUpdateStart: null }),
  setFeedbackError: (feedbackError) => set({ feedbackError, feedbackSuccess: '' }),
  setFeedbackSuccess: (feedbackSuccess) => set({ feedbackSuccess, feedbackError: '' }),
  clearFeedback: () => set({ feedbackError: '', feedbackSuccess: '' }),
  clearFeedbackError: () => set({ feedbackError: '' }),
  clearFeedbackSuccess: () => set({ feedbackSuccess: '' }),
}));
