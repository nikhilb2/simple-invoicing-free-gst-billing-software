import { create } from 'zustand';
import api from '../api/client';
import { identifyUser, resetAnalyticsUser } from '../lib/analytics';
import { postToNative } from '../lib/nativeBridge';
import { markSignedInBefore } from '../utils/nextPath';
import { queryClient } from '../lib/queryClient';
import type { AuthToken, UserProfile } from '../types/api';

function decodeEmailFromToken(token: string | null) {
  if (!token) {
    return null;
  }

  try {
    const [, payload] = token.split('.');
    const decoded = JSON.parse(atob(payload.replace(/-/g, '+').replace(/_/g, '/')));
    return typeof decoded.sub === 'string' ? decoded.sub : null;
  } catch {
    return null;
  }
}

type AuthState = {
  token: string | null;
  userEmail: string | null;
  /** Set by logout() when the server ended the session; cleared by the next sign-in. */
  sessionEnded: { email: string | null } | null;
  userRole: UserProfile['role'] | null;
  /** Role in the active company; null until /auth/me answers or without one. */
  companyRole: UserProfile['role'] | null;
  canManagePlatform: boolean;
  /** False from page load until /auth/me has answered (or failed). Role guards must wait for it. */
  profileLoaded: boolean;
  /** The account's name from /auth/me (the Google name, or the one confirmed at email sign-up). Null until it answers. */
  fullName: string | null;
  /** Undefined until /auth/me answers, null if the user has not answered the walkthrough. */
  firstInvoiceTourStatus: UserProfile['first_invoice_tour_status'] | undefined;
  setFirstInvoiceTourStatus: (status: UserProfile['first_invoice_tour_status']) => void;
  setToken: (token: string | null) => void;
  setUserRole: (role: UserProfile['role'] | null) => void;
  hydrateUserRole: () => Promise<void>;
  /** Stores a token pair however it was obtained (password login, OAuth exchange). */
  setSession: (tokens: AuthToken) => Promise<void>;
  login: (email: string, password: string) => Promise<void>;
  /**
   * `remote: false` skips the server's /auth/logout and `notifyNative: false`
   * skips the app's logout message: both are for a session the server already
   * rejected (see api/client.ts), where there is nothing to tell either.
   */
  logout: (options?: LogoutOptions) => void;
};

export type LogoutOptions = {
  remote?: boolean;
  notifyNative?: boolean;
  /** Set when the server ended the session; `Protected` then sends the visitor to sign in with a notice. */
  sessionEnded?: { email: string | null };
};

export const useAuthStore = create<AuthState>((set, get) => ({
  token: localStorage.getItem('token'),
  userEmail: decodeEmailFromToken(localStorage.getItem('token')),
  sessionEnded: null,
  userRole: null,
  companyRole: null,
  canManagePlatform: false,
  profileLoaded: false,
  fullName: null,
  firstInvoiceTourStatus: undefined,

  setFirstInvoiceTourStatus: (status) => set({ firstInvoiceTourStatus: status }),

  setToken: (token) => {
    set({ token, userEmail: decodeEmailFromToken(token) });
  },

  setUserRole: (role) => {
    set(role === null ? { userRole: null, companyRole: null, canManagePlatform: false, profileLoaded: false, fullName: null, firstInvoiceTourStatus: undefined } : { userRole: role });
  },

  hydrateUserRole: async () => {
    const token = get().token;
    if (!token) {
      set({ userRole: null, companyRole: null, canManagePlatform: false, profileLoaded: false, fullName: null, firstInvoiceTourStatus: undefined });
      return;
    }

    try {
      const res = await api.get<UserProfile>('/auth/me');
      if (typeof res.data.active_company_id === 'number') {
        localStorage.setItem('active_company_id', String(res.data.active_company_id));
      } else {
        localStorage.removeItem('active_company_id');
      }
      set({
        userRole: res.data.role,
        companyRole: res.data.company_role ?? null,
        canManagePlatform: res.data.can_manage_platform ?? false,
        profileLoaded: true,
        fullName: res.data.full_name ?? null,
        firstInvoiceTourStatus: res.data.first_invoice_tour_status ?? null,
      });
    } catch {
      set({ userRole: null, companyRole: null, canManagePlatform: false, profileLoaded: true, fullName: null, firstInvoiceTourStatus: undefined });
    }
  },

  setSession: async (tokens: AuthToken) => {
    localStorage.setItem('token', tokens.access_token);
    localStorage.setItem('refresh_token', tokens.refresh_token);
    markSignedInBefore();
    postToNative({ type: 'tokens', accessToken: tokens.access_token, refreshToken: tokens.refresh_token });
    const identifiedEmail = decodeEmailFromToken(tokens.access_token);
    set({
      token: tokens.access_token,
      userEmail: identifiedEmail,
      sessionEnded: null,
    });

    // Login, verified email sign-up and Google sign-up all establish identity
    // here. Committed events are captured server-side and keyed by this same
    // email, so identifying here is what puts
    // the recording of a session and the events that session produced on one
    // person instead of two. Role and active company are set on the person by
    // the backend, on login and on every company switch.
    if (identifiedEmail) {
      identifyUser(identifiedEmail, { email: identifiedEmail });
    }

    await get().hydrateUserRole();
  },

  login: async (email: string, password: string) => {
    const res = await api.post<AuthToken>('/auth/login', { email, password });
    await get().setSession(res.data);
  },

  logout: ({ remote = true, notifyNative = true, sessionEnded = undefined } = {}) => {
    // Fire-and-forget, and before the token is cleared: the endpoint exists so
    // that signing out is counted on the server like every other event. Nothing
    // waits on it and a failure is not worth surfacing -- the sign-out itself is
    // local, and happens either way.
    if (remote) {
      void api.post('/auth/logout').catch(() => undefined);
    }
    resetAnalyticsUser();
    localStorage.removeItem('token');
    localStorage.removeItem('refresh_token');
    localStorage.removeItem('active_company_id');
    // The mobile app holds its own copy of the tokens; this is what sends it
    // back to its native login screen instead of reloading us signed in.
    if (notifyNative) {
      postToNative({ type: 'logout' });
    }
    // Cached figures belong to the user who fetched them. The tab is not reloaded,
    // so without this the next login would show them until they went stale.
    queryClient.clear();
    set({ token: null, userEmail: null, sessionEnded: sessionEnded ?? null, userRole: null, companyRole: null, canManagePlatform: false, profileLoaded: false, fullName: null, firstInvoiceTourStatus: undefined });
  },
}));
