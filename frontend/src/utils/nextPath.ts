/**
 * The `?next=` return path, and the one place it is validated.
 *
 * `Protected` bounces an unauthenticated visitor to /login carrying where they
 * were headed, and LoginPage / `PublicOnly` send them back there once the
 * session exists. That round trip is what makes the OAuth consent screen
 * reachable at all: a connector drops the user on /oauth/consent?request_id=…,
 * and without the return path they would sign in and land on the dashboard with
 * the pending authorization request lost.
 *
 * It is also an open redirect waiting to happen. `next` arrives from the URL
 * bar, so anything that reaches `navigate()` unchecked lets a link that *looks*
 * like this app hand the visitor — freshly signed in, at their most trusting —
 * to an attacker's page. Hence one validator, used by every call site, that
 * accepts only a same-origin path:
 *
 *   - it must begin with exactly one '/', so `https://evil.com` and the
 *     protocol-relative `//evil.com` (which browsers resolve as a *host*) are
 *     both out;
 *   - no backslashes anywhere — several browsers normalise '\' to '/', making
 *     `/\evil.com` protocol-relative after the fact;
 *   - no control characters, which are stripped rather than rejected by URL
 *     parsers and can smuggle a leading '/' past a naive prefix check.
 *
 * Everything else is a path this app can route, and an unroutable one merely
 * lands on the catch-all redirect — not a security question.
 */

/** C0, DEL, and the Unicode line separators URL parsers quietly drop. */
const FORBIDDEN_CHARS = /[\u0000-\u001f\u007f\u2028\u2029]/;

/** Long enough for any real route, short enough not to be a payload. */
const MAX_LENGTH = 2048;

export const LOGIN_PATH = '/login';
export const NEXT_PARAM = 'next';
/** The `?reason=` code for a visitor sent to /login because their session ended. */
export const SESSION_EXPIRED_REASON = 'session_expired';

/** Whether `value` is a relative path this app may navigate to. */
export function isSafeNextPath(value: string | null | undefined): value is string {
  if (typeof value !== 'string') return false;
  if (value.length === 0 || value.length > MAX_LENGTH) return false;
  if (FORBIDDEN_CHARS.test(value)) return false;
  if (value.includes('\\')) return false;
  if (!value.startsWith('/')) return false;
  // '//host' is protocol-relative; '/../' is not a route this app serves.
  if (value.startsWith('//')) return false;
  return true;
}

/** `value` if it is safe to navigate to, else `fallback`. */
export function sanitizeNextPath(value: string | null | undefined, fallback = '/'): string {
  return isSafeNextPath(value) ? value : fallback;
}

/**
 * The /login URL that returns to `from` afterwards.
 *
 * A `from` of '/' is dropped: it is where login already lands, and carrying it
 * would put a redundant query string on the most-visited URL in the app.
 * `reason` is a fixed code (see LOGIN_ERROR_MESSAGES), never free text.
 */
export function loginPathWithNext(from: string | null | undefined, reason?: string): string {
  const params = new URLSearchParams();
  if (isSafeNextPath(from) && from !== '/') params.set(NEXT_PARAM, from);
  if (reason) params.set('reason', reason);
  const query = params.toString();
  return query ? `${LOGIN_PATH}?${query}` : LOGIN_PATH;
}

export const REGISTER_PATH = '/register';
/** localStorage flag: this browser has held a session at least once. Never cleared on sign-out. */
export const SIGNED_IN_BEFORE_KEY = 'si_signed_in_before';

/** Records that this browser has signed in. Storage that cannot be written is ignored. */
export function markSignedInBefore(): void {
  try {
    localStorage.setItem(SIGNED_IN_BEFORE_KEY, '1');
  } catch {
    /* private mode or blocked storage: the visitor just counts as first-time */
  }
}

/**
 * Whether this browser has signed in before: the flag, or tokens left in storage
 * by a build that predates the flag. Unreadable storage counts as first-time.
 */
export function hasSignedInBefore(): boolean {
  try {
    return (
      localStorage.getItem(SIGNED_IN_BEFORE_KEY) === '1' ||
      !!localStorage.getItem('token') ||
      !!localStorage.getItem('refresh_token')
    );
  } catch {
    return false;
  }
}

type LandingInput = {
  pathname: string;
  search: string;
  sessionEnded: boolean;
  signedInBefore: boolean;
  signupEnabled: boolean;
};

/**
 * Where a signed-out visitor goes.
 *
 * Someone who opens the bare home page (`/`, any query string, so UTM tags
 * survive) in a browser that has never signed in, on a deployment that accepts
 * sign-ups, wants Create account. Every other case (deep links, ended sessions,
 * returning users, sign-up off) goes to /login with the return path, as before.
 */
export function signedOutLandingPath({ pathname, search, sessionEnded, signedInBefore, signupEnabled }: LandingInput): string {
  if (pathname === '/' && !sessionEnded && !signedInBefore && signupEnabled) {
    return `${REGISTER_PATH}${search}`;
  }
  return loginPathWithNext(`${pathname}${search}`, sessionEnded ? SESSION_EXPIRED_REASON : undefined);
}
