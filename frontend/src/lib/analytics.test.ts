import { afterEach, expect, it, vi } from 'vitest';

const sdk = vi.hoisted(() => ({ init: vi.fn(), capture: vi.fn(), identify: vi.fn() }));
vi.mock('posthog-js', () => ({ default: sdk }));

afterEach(() => {
  vi.unstubAllEnvs();
  vi.clearAllMocks();
  vi.resetModules();
});

it.each(['', 'fixture-token'])('does nothing with incomplete configuration (%s)', async (token) => {
  vi.stubEnv('VITE_POSTHOG_PROJECT_TOKEN', token);
  vi.stubEnv('VITE_POSTHOG_HOST', '');
  const analytics = await import('./analytics');
  analytics.initAnalytics();
  analytics.captureEvent('ledger_quick_create_opened');
  analytics.identifyUser('test@example.invalid');
  expect(sdk.init).not.toHaveBeenCalled();
  expect(sdk.capture).not.toHaveBeenCalled();
  expect(sdk.identify).not.toHaveBeenCalled();
});

it('sends the browser-only event only once analytics is initialized', async () => {
  vi.stubEnv('VITE_POSTHOG_PROJECT_TOKEN', 'fixture-token');
  vi.stubEnv('VITE_POSTHOG_HOST', 'https://analytics.example.invalid');
  const analytics = await import('./analytics');
  analytics.captureEvent('ledger_quick_create_opened');
  expect(sdk.capture).not.toHaveBeenCalled();
  analytics.initAnalytics();
  analytics.captureEvent('ledger_quick_create_opened');
  expect(sdk.capture.mock.calls).toEqual([['ledger_quick_create_opened', undefined]]);
});
