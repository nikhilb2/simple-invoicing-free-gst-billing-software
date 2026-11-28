import { describe, expect, test } from 'vitest';
import { shouldDismissOnDialogOpen, watchUserInput } from './toastDialog';

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

  test('a dialog that opens with no tap or key press since the toast showed keeps it (issue 1129)', () => {
    // The challan preview mounts when its fetch returns: ~15 ms on fast Wi-Fi, 2 s or more on slow 4G.
    expect(
      shouldDismissOnDialogOpen({ successShownBeforeOpen: true, dialogCountBefore: 0, dialogCountAfter: 1, userActedSinceShown: false }),
    ).toBe(false);
  });

  test('a dialog the user opens after the toast showed dismisses it (issue 1110)', () => {
    expect(
      shouldDismissOnDialogOpen({ successShownBeforeOpen: true, dialogCountBefore: 0, dialogCountAfter: 1, userActedSinceShown: true }),
    ).toBe(true);
  });

  test('an error toast is kept even after user input', () => {
    expect(
      shouldDismissOnDialogOpen({
        kind: 'error',
        successShownBeforeOpen: true,
        dialogCountBefore: 0,
        dialogCountAfter: 1,
        userActedSinceShown: true,
      }),
    ).toBe(false);
  });
});

describe('watchUserInput', () => {
  test('no input: not acted, however long it waits', () => {
    const target = new EventTarget();
    const watch = watchUserInput(target);
    expect(watch.acted()).toBe(false);
    target.dispatchEvent(new Event('scroll'));
    target.dispatchEvent(new Event('pointermove'));
    expect(watch.acted()).toBe(false);
    watch.stop();
  });

  test('a pointerdown or keydown counts as user input', () => {
    for (const type of ['pointerdown', 'keydown']) {
      const target = new EventTarget();
      const watch = watchUserInput(target);
      target.dispatchEvent(new Event(type));
      expect(watch.acted(), type).toBe(true);
      watch.stop();
    }
  });

  test('input after stop is ignored', () => {
    const target = new EventTarget();
    const watch = watchUserInput(target);
    watch.stop();
    target.dispatchEvent(new Event('pointerdown'));
    expect(watch.acted()).toBe(false);
  });

  test('the toast flow: preview mounts late with no input → kept; user taps then opens a dialog → dismissed', () => {
    const target = new EventTarget();
    const watch = watchUserInput(target);
    // Challan saved, toast shows, preview mounts 2,000 ms later with no tap in between.
    expect(
      shouldDismissOnDialogOpen({ successShownBeforeOpen: true, dialogCountBefore: 0, dialogCountAfter: 1, userActedSinceShown: watch.acted() }),
    ).toBe(false);
    // The user then taps a button that opens another dialog (issue 1110's "New product").
    target.dispatchEvent(new Event('pointerdown'));
    expect(
      shouldDismissOnDialogOpen({ successShownBeforeOpen: true, dialogCountBefore: 1, dialogCountAfter: 2, userActedSinceShown: watch.acted() }),
    ).toBe(true);
    watch.stop();
  });
});
