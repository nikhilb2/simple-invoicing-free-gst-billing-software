import { beforeEach, describe, expect, it, vi } from 'vitest';

const saved = vi.hoisted(() => [] as string[]);

vi.mock('../api/auth', () => ({
  saveFirstInvoiceTourStatus: (status: string) => {
    saved.push(status);
    return Promise.resolve(status);
  },
}));

vi.mock('./useAuthStore', () => {
  const state = {
    userEmail: 'owner@example.invalid',
    firstInvoiceTourStatus: null as string | null,
    setFirstInvoiceTourStatus: (status: string) => {
      state.firstInvoiceTourStatus = status;
    },
  };
  return { useAuthStore: { getState: () => state } };
});

import { useFirstInvoiceTourStore } from './useFirstInvoiceTourStore';
import { useAuthStore } from './useAuthStore';

beforeEach(() => {
  saved.length = 0;
  useFirstInvoiceTourStore.setState({ phase: 'idle', owner: null });
});

describe('the first-invoice walkthrough can be started again', () => {
  it('starts after "Exit walkthrough" was recorded as skipped', () => {
    const tour = useFirstInvoiceTourStore.getState();
    tour.start();
    expect(useFirstInvoiceTourStore.getState()).toMatchObject({ phase: 'running', owner: 'owner@example.invalid' });

    tour.exit();
    expect(useFirstInvoiceTourStore.getState().phase).toBe('idle');
    expect(useAuthStore.getState().firstInvoiceTourStatus).toBe('skipped');
    expect(saved).toEqual(['skipped']);

    // "Show me how" on the composer.
    useFirstInvoiceTourStore.getState().start();
    expect(useFirstInvoiceTourStore.getState()).toMatchObject({ phase: 'running', owner: 'owner@example.invalid' });
  });

  it('records "completed" when the restarted walkthrough ends in an invoice', () => {
    const tour = useFirstInvoiceTourStore.getState();
    tour.start();
    tour.exit();
    tour.start();
    tour.invoiceCreated();
    expect(useFirstInvoiceTourStore.getState().phase).toBe('done');
    expect(saved).toEqual(['skipped', 'completed']);
  });
});
