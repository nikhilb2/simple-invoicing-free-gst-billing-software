import { describe, expect, it, vi } from 'vitest';
import { focusAfterCancelDialog } from './creditNoteCancelFocus';

const button = (visible: boolean) => ({ focus: vi.fn(), offsetParent: visible ? {} : null });

function root(trigger: ReturnType<typeof button> | null, rowButtons: ReturnType<typeof button>[]) {
  return {
    querySelector: vi.fn(() => trigger),
    querySelectorAll: vi.fn(() => rowButtons),
  } as unknown as Parameters<typeof focusAfterCancelDialog>[0];
}

describe('focusAfterCancelDialog', () => {
  it('returns to the preview menu trigger, not the row behind it, while the preview is still open', () => {
    const trigger = button(true);
    const row = button(true);
    focusAfterCancelDialog(root(trigger, [row]), 7);
    expect(trigger.focus).toHaveBeenCalledTimes(1);
    expect(row.focus).not.toHaveBeenCalled();
  });

  it('goes to the first visible row or card button once the preview is gone (no trigger in the DOM)', () => {
    const hidden = button(false);
    const shown = button(true);
    focusAfterCancelDialog(root(null, [hidden, shown]), 7);
    expect(hidden.focus).not.toHaveBeenCalled();
    expect(shown.focus).toHaveBeenCalledTimes(1);
  });
});
