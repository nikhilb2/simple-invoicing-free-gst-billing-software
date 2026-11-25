type FocusRoot = Pick<Document, 'querySelector' | 'querySelectorAll'>;

/**
 * Where focus goes when the cancel confirmation closes.
 *
 * If the preview is still open (the user kept the note), it goes back to the
 * preview's "More actions" trigger, not the row behind the dialog. Otherwise
 * the preview is gone, so it goes to the note's table row or phone card,
 * whichever is showing.
 */
export function focusAfterCancelDialog(root: FocusRoot, noteId: number): void {
  const trigger = root.querySelector<HTMLButtonElement>('[aria-labelledby="credit-note-preview-title"] button[aria-label="More actions"]');
  if (trigger) {
    trigger.focus();
    return;
  }
  Array.from(root.querySelectorAll<HTMLButtonElement>(`#credit-note-${noteId} button, #credit-note-${noteId}-card button`))
    .find((button) => button.offsetParent !== null)?.focus();
}
