import { readFileSync } from 'node:fs';
import { AxiosError, AxiosHeaders, type AxiosResponse } from 'axios';
import { describe, expect, it } from 'vitest';
import { busyClass, createSubmitGuard, isConnectionOrServerError, SAVE_FAILED_MESSAGE } from './saveFeedback';

function httpError(status: number) {
  const config = { headers: new AxiosHeaders() };
  const response = { status, statusText: '', headers: {}, config, data: {} } as AxiosResponse;
  return new AxiosError('failed', String(status), config, null, response);
}

describe('isConnectionOrServerError', () => {
  it('is true when no answer came back (offline, timeout)', () => {
    expect(isConnectionOrServerError(new AxiosError('Network Error', 'ERR_NETWORK'))).toBe(true);
  });

  it.each([500, 502, 503, 504])('is true for a %i', (status) => {
    expect(isConnectionOrServerError(httpError(status))).toBe(true);
  });

  it.each([400, 401, 403, 409, 422])('is false for a %i: those have their own message', (status) => {
    expect(isConnectionOrServerError(httpError(status))).toBe(false);
  });

  it('is false for anything that is not a request error', () => {
    expect(isConnectionOrServerError(new Error('boom'))).toBe(false);
    expect(isConnectionOrServerError(null)).toBe(false);
  });
});

describe('createSubmitGuard (can’t run twice)', () => {
  it('lets only the first of two quick taps through', () => {
    const guard = createSubmitGuard();
    expect(guard.busy).toBe(false);
    expect(guard.claim()).toBe(true);
    expect(guard.busy).toBe(true);
    expect(guard.claim()).toBe(false);
    expect(guard.claim()).toBe(false);
  });

  it('lets the person try again after a failure', () => {
    const guard = createSubmitGuard();
    guard.claim();
    guard.release();
    expect(guard.busy).toBe(false);
    expect(guard.claim()).toBe(true);
  });

  it('keeps one guard per form', () => {
    const a = createSubmitGuard();
    const b = createSubmitGuard();
    a.claim();
    expect(b.claim()).toBe(true);
  });
});

describe('busy buttons', () => {
  it('adds is-busy only while busy', () => {
    expect(busyClass(true)).toBe(' is-busy');
    expect(busyClass(false)).toBe('');
  });

  it('keep their colour and the wait cursor (styles)', () => {
    const css = readFileSync(new URL('../styles.css', import.meta.url), 'utf8');
    const rule = css.match(/\n\.button:disabled\.is-busy \{([^}]*)\}/)?.[1] ?? '';
    expect(rule).toMatch(/opacity:\s*1;/);
    expect(rule).toMatch(/filter:\s*none;/);
    expect(rule).toMatch(/cursor:\s*wait;/);
  });

  it('says what to do when the save fails', () => {
    expect(SAVE_FAILED_MESSAGE).toBe('Couldn’t save. Check your internet and try again.');
  });
});
