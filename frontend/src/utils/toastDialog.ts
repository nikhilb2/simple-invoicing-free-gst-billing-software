export const DIALOG_SELECTOR = '.modal-overlay';

export type DialogOpenInput = {
  /** Which toast is being judged. Only a success toast is ever cleared by a dialog opening. */
  kind?: 'success' | 'error';
  /** The toast was already showing before the dialog count rose. */
  successShownBeforeOpen: boolean;
  dialogCountBefore: number;
  dialogCountAfter: number;
  /**
   * A tap, click or key press happened after the toast first showed (issue 1129). A dialog that
   * opens with no input since then is part of the same action (the challan preview mounting after
   * its fetch, however slow) and leaves the toast alone. Left out, the dialog counts as user-opened.
   */
  userActedSinceShown?: boolean;
};

/** Inputs that mean the user, not the app, may have opened the next dialog. */
export const USER_INPUT_EVENTS = ['pointerdown', 'keydown'] as const;

// An options object, not `true`: Node's EventTarget (unit tests) only matches the object form on remove.
const CAPTURE: AddEventListenerOptions = { capture: true };

/**
 * Notes whether the user tapped, clicked or pressed a key on `target` since this was called.
 * Listens in the capture phase, so a handler that stops propagation can't hide the input.
 */
export function watchUserInput(target: EventTarget): { acted: () => boolean; stop: () => void } {
  let acted = false;
  const onInput = () => {
    acted = true;
  };
  USER_INPUT_EVENTS.forEach((type) => target.addEventListener(type, onInput, CAPTURE));
  return {
    acted: () => acted,
    stop: () => USER_INPUT_EVENTS.forEach((type) => target.removeEventListener(type, onInput, CAPTURE)),
  };
}

/**
 * A success toast that was already visible when the user opens a dialog is dismissed (issue 1110),
 * so it does not cover the dialog's last fields. A dialog that opens by itself, with no tap or key
 * press since the toast showed, keeps it (issue 1129). A success that arrives after the dialog
 * opened stays, and an error toast is never touched.
 */
export function shouldDismissOnDialogOpen({
  kind = 'success',
  successShownBeforeOpen,
  dialogCountBefore,
  dialogCountAfter,
  userActedSinceShown = true,
}: DialogOpenInput): boolean {
  return kind === 'success' && successShownBeforeOpen && userActedSinceShown && dialogCountAfter > dialogCountBefore;
}
