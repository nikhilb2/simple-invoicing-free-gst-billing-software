export const SUCCESS_TOAST_MS = 5000;
/** Errors stay longer than successes so they can be read, but they do clear (issue 956). */
export const ERROR_TOAST_MS = 8000;

/** Calls `clear` once after `durationMs`; returns a cleanup that cancels it. */
export function scheduleToastDismiss(durationMs: number, clear: () => void): () => void {
  const timeoutId = setTimeout(clear, durationMs);
  return () => clearTimeout(timeoutId);
}
