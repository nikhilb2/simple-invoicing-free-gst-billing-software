import axios from 'axios';
import { apiBaseURL, getApiErrorMessage } from '../api/client';
import { getStoredUtm, type UtmParams } from '../lib/utm';
import { SESSION_EXPIRED_REASON, sanitizeNextPath } from './nextPath';

/**
 * Where the browser goes to start a provider sign-in.
 *
 * A full-page navigation, never an XHR: the backend answers with a 302 to the
 * provider, and the provider's consent screen has to own the tab. `next` goes
 * through the same validator as every other return path.
 *
 * The visitor's UTM tags ride along as query parameters: there is no request
 * body to put them in, and the backend carries them to the callback so a
 * first-time Google sign-in is attributed like a password sign-up.
 */
export function oauthLoginUrl(
  providerId: string,
  next: string | null | undefined,
  utm: UtmParams = getStoredUtm(),
): string {
  const base = apiBaseURL.replace(/\/+$/, '');
  const params = new URLSearchParams({ next: sanitizeNextPath(next), ...utm });
  return `${base}/auth/oauth/${encodeURIComponent(providerId)}/login?${params.toString()}`;
}

/** Messages for the `?error=` codes the OAuth callback redirects to /login with. */
const LOGIN_ERROR_MESSAGES: Record<string, string> = {
  signup_disabled: 'Sign-up is not open for this account. Ask an administrator for access.',
  email_not_verified: 'Please verify your email address before signing in.',
  account_inactive: 'This account has been deactivated.',
  oauth_failed: 'Sign-in with the provider did not complete. Please try again.',
  session_expired: 'You were signed out. Sign in again to continue.',
};

/** The sign-in page header for a `?reason=` code, or null for none or an unknown one. */
export function loginReasonNotice(reason: string | null | undefined) {
  if (reason !== SESSION_EXPIRED_REASON) return null;
  return { eyebrow: 'Session ended', title: 'Sign in again', copy: LOGIN_ERROR_MESSAGES[reason] };
}

export function loginErrorMessage(code: string | null | undefined): string {
  if (!code) return '';
  return LOGIN_ERROR_MESSAGES[code] ?? 'Unable to sign in. Please try again.';
}

/** Message for a failed auth request, with the 429 case spelled out. */
export function authErrorMessage(error: unknown, fallback: string): string {
  if (axios.isAxiosError(error) && error.response?.status === 429) {
    return 'Too many attempts. Please wait a few minutes and try again.';
  }
  return getApiErrorMessage(error, fallback);
}

/** Where /auth/callback sends the visitor once the one-time code is exchanged. */
export function callbackNextPath(params: URLSearchParams): string {
  return sanitizeNextPath(params.get('next'));
}

export const OAUTH_FAILED_PATH = '/login?error=oauth_failed';
