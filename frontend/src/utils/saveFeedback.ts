import axios from 'axios';

/**
 * Shown under a Save button when the request never got an answer, or the server
 * failed (#963, "Save always answers"). The typed values stay in the form.
 */
export const SAVE_FAILED_MESSAGE = 'Couldn’t save. Check your internet and try again.';

/** A network failure (no response at all) or a 5xx: nothing the person typed is wrong. */
export function isConnectionOrServerError(error: unknown): boolean {
  if (!axios.isAxiosError(error)) return false;
  if (!error.response) return true;
  return error.response.status >= 500;
}

/** The class suffix for a Save button that is waiting on the server: it keeps its colour. */
export function busyClass(busy: boolean): string {
  return busy ? ' is-busy' : '';
}

export type SubmitGuard = {
  /** True while a save is on its way. */
  readonly busy: boolean;
  /** Takes the guard. False when a save is already on its way: do nothing then. */
  claim: () => boolean;
  /** After a failure, so the person can try again. Never on success. */
  release: () => void;
};

/**
 * "Can't run twice" (#963): a flag that is set synchronously, before the first
 * await, so a second tap in the same render cannot send a second request. React
 * state such as `submitting` arrives one render late. Keep one per form with
 * `useState(createSubmitGuard)`. On success leave it claimed until the next
 * screen has opened.
 */
export function createSubmitGuard(): SubmitGuard {
  let busy = false;
  return {
    get busy() {
      return busy;
    },
    claim() {
      if (busy) return false;
      busy = true;
      return true;
    },
    release() {
      busy = false;
    },
  };
}
