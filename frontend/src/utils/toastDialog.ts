export const DIALOG_SELECTOR = '.modal-overlay';

export type DialogOpenInput = {
  /** Which toast is being judged. Only a success toast is ever cleared by a dialog opening. */
  kind?: 'success' | 'error';
  /** The toast was already showing before the dialog count rose. */
  successShownBeforeOpen: boolean;
  dialogCountBefore: number;
  dialogCountAfter: number;
};

/**
 * A success toast that was already visible when a dialog opens is dismissed (issue 1110), so it
 * does not cover the dialog's last fields. A success that arrives after the dialog opened stays,
 * and an error toast is never touched.
 */
export function shouldDismissOnDialogOpen({
  kind = 'success',
  successShownBeforeOpen,
  dialogCountBefore,
  dialogCountAfter,
}: DialogOpenInput): boolean {
  return kind === 'success' && successShownBeforeOpen && dialogCountAfter > dialogCountBefore;
}
