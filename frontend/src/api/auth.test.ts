import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import type { InternalAxiosRequestConfig } from 'axios';
import api from './client';
import { registerAccount } from './auth';

/* Node environment, no DOM: storage is an in-memory stub and the transport is an
   adapter that records the request instead of sending it. */

let store: Record<string, string> = {};
let sent: InternalAxiosRequestConfig | null = null;

beforeEach(() => {
  store = {};
  sent = null;
  (globalThis as { localStorage?: Storage }).localStorage = {
    getItem: (key: string) => (key in store ? store[key] : null),
    setItem: (key: string, value: string) => void (store[key] = String(value)),
    removeItem: (key: string) => void delete store[key],
  } as Storage;
  api.defaults.adapter = async (config) => {
    sent = config;
    return { data: { detail: 'ok' }, status: 202, statusText: 'Accepted', headers: {}, config };
  };
});

afterEach(() => {
  delete (globalThis as { localStorage?: Storage }).localStorage;
});

describe('registerAccount', () => {
  it('sends the stored UTM tags with the registration', async () => {
    store.si_utm = JSON.stringify({ utm_source: 'youtube', utm_campaign: 'launch' });

    await registerAccount({ email: 'a@example.com', full_name: 'A' });

    expect(sent?.url).toBe('/auth/register');
    expect(JSON.parse(sent?.data as string)).toEqual({
      email: 'a@example.com',
      full_name: 'A',
      utm: { utm_source: 'youtube', utm_campaign: 'launch' },
    });
  });

  it('sends an empty utm when the visitor arrived without tags', async () => {
    await registerAccount({ email: 'a@example.com', full_name: 'A' });

    expect(JSON.parse(sent?.data as string).utm).toEqual({});
  });
});
