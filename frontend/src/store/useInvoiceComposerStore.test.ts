import { beforeEach, describe, expect, it, vi } from 'vitest';
import { captureEvent } from '../lib/analytics';
import { useInvoiceComposerStore } from './useInvoiceComposerStore';

vi.mock('../lib/analytics', () => ({ captureEvent: vi.fn() }));

it('records each opening once with no customer properties, including after closing', () => {
  useInvoiceComposerStore.getState().closeLedgerCreateModal();
  vi.mocked(captureEvent).mockClear();
  useInvoiceComposerStore.setState({ selectedLedgerId: '7', feedbackSuccess: 'Private customer name' });
  useInvoiceComposerStore.getState().openLedgerCreateModal();
  useInvoiceComposerStore.getState().openLedgerCreateModal();
  expect(useInvoiceComposerStore.getState().showLedgerCreateModal).toBe(true);
  expect(vi.mocked(captureEvent).mock.calls).toEqual([['ledger_quick_create_opened']]);
  useInvoiceComposerStore.getState().closeLedgerCreateModal();
  useInvoiceComposerStore.getState().openLedgerCreateModal();
  expect(vi.mocked(captureEvent).mock.calls).toEqual([['ledger_quick_create_opened'], ['ledger_quick_create_opened']]);
  useInvoiceComposerStore.getState().closeLedgerCreateModal();
});

describe('useInvoiceComposerStore feedback', () => {
  beforeEach(() => useInvoiceComposerStore.getState().clearFeedback());

  it('clearFeedbackError leaves success untouched', () => {
    useInvoiceComposerStore.setState({ feedbackError: 'bad', feedbackSuccess: 'good' });
    useInvoiceComposerStore.getState().clearFeedbackError();
    expect(useInvoiceComposerStore.getState().feedbackError).toBe('');
    expect(useInvoiceComposerStore.getState().feedbackSuccess).toBe('good');
  });

  it('clearFeedbackSuccess leaves error untouched', () => {
    useInvoiceComposerStore.setState({ feedbackError: 'bad', feedbackSuccess: 'good' });
    useInvoiceComposerStore.getState().clearFeedbackSuccess();
    expect(useInvoiceComposerStore.getState().feedbackSuccess).toBe('');
    expect(useInvoiceComposerStore.getState().feedbackError).toBe('bad');
  });
});
