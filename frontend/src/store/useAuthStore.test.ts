import type { AxiosResponse } from 'axios';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import api from '../api/client';
import { queryClient } from '../lib/queryClient';
import { identifyUser } from '../lib/analytics';
import { exchangeOAuthCode, verifyEmail } from '../api/auth';
import { verifiedSession } from '../utils/verifyEmailForm';
import { useAuthStore } from './useAuthStore';

vi.mock('../lib/analytics', () => ({
  identifyUser: vi.fn(), resetAnalyticsUser: vi.fn(), getSessionId: () => null,
}));

/* The store reads localStorage the moment its module loads, so the in-memory
   stub has to be in place before the imports above run. */
const store = vi.hoisted(() => {
  const data: Record<string, string> = {};
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: {
      getItem: (key: string) => (key in data ? data[key] : null),
      setItem: (key: string, value: string) => { data[key] = String(value); },
      removeItem: (key: string) => { delete data[key]; },
    },
  });
  return data;
});

const postMessage = vi.fn();

function sentMessages() {
  return postMessage.mock.calls.map(([data]) => JSON.parse(data as string));
}

beforeEach(() => {
  vi.stubGlobal('window', { ReactNativeWebView: { postMessage } });
  api.defaults.adapter = async (config): Promise<AxiosResponse> => {
    const data = config.url === '/auth/login'
      ? { access_token: 'access', refresh_token: 'refresh' }
      : { role: 'admin', active_company_id: null };
    return { data, status: 200, statusText: 'OK', headers: {}, config };
  };
});

afterEach(() => {
  vi.mocked(identifyUser).mockClear();
  vi.unstubAllGlobals();
  postMessage.mockReset();
  for (const key of Object.keys(store)) {
    delete store[key];
  }
});

describe('auth store and the native bridge', () => {
  it.each(['email', 'google'] as const)('identifies the confirmed %s sign-up through setSession', async (kind) => {
    const email = 'signup@example.invalid';
    const tokens = { access_token: `fixture.${btoa(JSON.stringify({ sub: email }))}.fixture`, refresh_token: 'refresh', token_type: 'bearer' };
    api.defaults.adapter = async (config): Promise<AxiosResponse> => ({
      data: config.url === '/auth/me' ? { role: 'admin', active_company_id: null } : tokens,
      status: 200, statusText: 'OK', headers: {}, config,
    });
    const response = kind === 'email'
      ? verifiedSession(await verifyEmail('verification-fixture', 'Password-fixture', 'Demo'))
      : await exchangeOAuthCode('oauth-fixture');
    // These are the same public API and shared session path used by the two pages.
    expect(response).not.toBeNull();
    await useAuthStore.getState().setSession(response!);
    expect(identifyUser).toHaveBeenCalledExactlyOnceWith(email, { email });
    expect(useAuthStore.getState().userEmail).toBe(email);
  });

  it('posts the new pair on login', async () => {
    await useAuthStore.getState().login('a@example.com', 'secret');

    expect(store).toMatchObject({ token: 'access', refresh_token: 'refresh' });
    expect(sentMessages()).toEqual([{ type: 'tokens', accessToken: 'access', refreshToken: 'refresh' }]);
  });

  it('posts logout once storage is cleared', () => {
    store.token = 'access';
    store.refresh_token = 'refresh';
    // Snapshotted rather than asserted inside the mock: postToNative swallows
    // anything postMessage throws, a failed expect included.
    let storageWhenPosted: Record<string, string> | null = null;
    postMessage.mockImplementation(() => {
      storageWhenPosted = { ...store };
    });

    useAuthStore.getState().logout();

    expect(sentMessages()).toEqual([{ type: 'logout' }]);
    expect(storageWhenPosted).toEqual({});
    expect(useAuthStore.getState().token).toBeNull();
  });

  it('logout drops every cached query, so the next login cannot see this user\'s figures', () => {
    queryClient.setQueryData(['gstr3b', 'worksheet', '2026-06-01', '2026-06-30'], { total: 1 });

    useAuthStore.getState().logout();

    expect(queryClient.getQueryCache().getAll()).toHaveLength(0);
  });

  it('setSession stores the pair, tells the native bridge and records the active company', async () => {
    api.defaults.adapter = async (config): Promise<AxiosResponse> => ({
      data: { role: 'staff', active_company_id: 7 },
      status: 200,
      statusText: 'OK',
      headers: {},
      config,
    });

    await useAuthStore.getState().setSession({ access_token: 'a2', refresh_token: 'r2', token_type: 'bearer' });

    expect(store).toMatchObject({ token: 'a2', refresh_token: 'r2', active_company_id: '7' });
    expect(sentMessages()).toEqual([{ type: 'tokens', accessToken: 'a2', refreshToken: 'r2' }]);
    expect(useAuthStore.getState()).toMatchObject({ token: 'a2', userRole: 'staff' });
  });

  it('setSession marks the browser as signed in before, and logout keeps the mark', async () => {
    await useAuthStore.getState().setSession({ access_token: 'a5', refresh_token: 'r5', token_type: 'bearer' });
    expect(store.si_signed_in_before).toBe('1');

    useAuthStore.getState().logout();
    expect(store.token).toBeUndefined();
    expect(store.si_signed_in_before).toBe('1');
  });

  it('keeps the account name from /auth/me for the first-run Business name, and drops it on logout', async () => {
    api.defaults.adapter = async (config): Promise<AxiosResponse> => ({
      data: { role: 'admin', active_company_id: null, full_name: 'Ravi Kumar' },
      status: 200,
      statusText: 'OK',
      headers: {},
      config,
    });

    await useAuthStore.getState().setSession({ access_token: 'a4', refresh_token: 'r4', token_type: 'bearer' });
    expect(useAuthStore.getState().fullName).toBe('Ravi Kumar');

    useAuthStore.getState().logout();
    expect(useAuthStore.getState().fullName).toBeNull();
  });

  it('setSession clears a stale active company when the user has none', async () => {
    store.active_company_id = '99';

    await useAuthStore.getState().setSession({ access_token: 'a3', refresh_token: 'r3', token_type: 'bearer' });

    expect(store.active_company_id).toBeUndefined();
  });
});
