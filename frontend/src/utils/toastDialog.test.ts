import { describe, expect, test } from 'vitest';
import { shouldDismissOnDialogOpen } from './toastDialog';

describe('shouldDismissOnDialogOpen', () => {
  test('a success shown before a dialog opens is dismissed', () => {
    expect(shouldDismissOnDialogOpen({ successShownBeforeOpen: true, dialogCountBefore: 0, dialogCountAfter: 1 })).toBe(true);
  });

  test('a dialog opening over an already open one also dismisses', () => {
    expect(shouldDismissOnDialogOpen({ successShownBeforeOpen: true, dialogCountBefore: 1, dialogCountAfter: 2 })).toBe(true);
  });

  test('a success that arrived after the dialog opened is kept', () => {
    expect(shouldDismissOnDialogOpen({ successShownBeforeOpen: false, dialogCountBefore: 0, dialogCountAfter: 1 })).toBe(false);
  });

  test('an error toast is never dismissed', () => {
    expect(
      shouldDismissOnDialogOpen({ kind: 'error', successShownBeforeOpen: true, dialogCountBefore: 0, dialogCountAfter: 1 }),
    ).toBe(false);
  });

  test('no increase in dialogs keeps the toast', () => {
    expect(shouldDismissOnDialogOpen({ successShownBeforeOpen: true, dialogCountBefore: 1, dialogCountAfter: 1 })).toBe(false);
    expect(shouldDismissOnDialogOpen({ successShownBeforeOpen: true, dialogCountBefore: 1, dialogCountAfter: 0 })).toBe(false);
  });
});
