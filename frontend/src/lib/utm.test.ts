import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { captureUtm, getStoredUtm, parseUtm } from './utm';

function installLocalStorage() {
  const store = new Map<string, string>();
  (globalThis as { localStorage?: Storage }).localStorage = {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => void store.set(key, value),
    removeItem: (key: string) => void store.delete(key),
    clear: () => store.clear(),
    key: () => null,
    get length() {
      return store.size;
    },
  } as Storage;
}

describe('parseUtm', () => {
  it('keeps every utm_* tag and nothing else', () => {
    expect(
      parseUtm(
        '?utm_source=google&utm_medium=cpc&utm_campaign=gst&utm_term=billing&utm_content=ad1&utm_id=42&utm_custom=x&gclid=abc&page=2',
      ),
    ).toEqual({
      utm_source: 'google',
      utm_medium: 'cpc',
      utm_campaign: 'gst',
      utm_term: 'billing',
      utm_content: 'ad1',
      utm_id: '42',
      utm_custom: 'x',
    });
  });

  it('lowercases keys and drops blank values', () => {
    expect(parseUtm('?UTM_Source=Insta&utm_medium=%20')).toEqual({ utm_source: 'Insta' });
  });
});

describe('captureUtm / getStoredUtm', () => {
  beforeEach(installLocalStorage);
  afterEach(() => {
    delete (globalThis as { localStorage?: Storage }).localStorage;
  });

  it('stores the tags from the landing URL', () => {
    captureUtm('?utm_source=youtube&utm_campaign=launch');
    expect(getStoredUtm()).toEqual({ utm_source: 'youtube', utm_campaign: 'launch' });
  });

  it('keeps the earlier tags when a later load has none', () => {
    captureUtm('?utm_source=youtube');
    captureUtm('?page=2');
    expect(getStoredUtm()).toEqual({ utm_source: 'youtube' });
  });

  it('replaces the tags when a later load has new ones', () => {
    captureUtm('?utm_source=youtube&utm_campaign=launch');
    captureUtm('?utm_source=google');
    expect(getStoredUtm()).toEqual({ utm_source: 'google' });
  });

  it('survives the logged-out redirect that drops the query string', () => {
    // main.tsx runs captureUtm() before the router mounts, so a link such as
    // /invoices?utm_source=x is saved before <Protected> redirects to /login.
    captureUtm('?utm_source=x');
    captureUtm('');
    expect(getStoredUtm()).toEqual({ utm_source: 'x' });
  });

  it('returns nothing for a corrupt stored value', () => {
    localStorage.setItem('si_utm', 'not json');
    expect(getStoredUtm()).toEqual({});
  });
});
