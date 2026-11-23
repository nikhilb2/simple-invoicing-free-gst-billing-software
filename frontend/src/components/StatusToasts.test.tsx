import { readFileSync } from 'node:fs';
import { renderToString } from 'react-dom/server';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import StatusToasts from './StatusToasts';
import { ERROR_TOAST_MS, SUCCESS_TOAST_MS, scheduleToastDismiss } from '../utils/toastTiming';

const styles = readFileSync(new URL('../styles.css', import.meta.url), 'utf8');

/** The body of the first rule whose selector matches `selector` exactly, after `from`. */
function ruleBody(selector: string, from = 0): string {
  const start = styles.indexOf(`${selector} {`, from);
  expect(start, `rule ${selector}`).toBeGreaterThanOrEqual(0);
  return styles.slice(start, styles.indexOf('}', start));
}

describe('StatusToasts timing', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  test('an error toast clears itself, later than a success does', () => {
    expect(ERROR_TOAST_MS).toBe(8000);
    expect(SUCCESS_TOAST_MS).toBe(5000);

    const clear = vi.fn();
    scheduleToastDismiss(ERROR_TOAST_MS, clear);

    vi.advanceTimersByTime(ERROR_TOAST_MS - 1);
    expect(clear).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(clear).toHaveBeenCalledTimes(1);
  });

  test('the cleanup cancels a pending dismissal', () => {
    const clear = vi.fn();
    const cancel = scheduleToastDismiss(1000, clear);

    cancel();
    vi.advanceTimersByTime(5000);
    expect(clear).not.toHaveBeenCalled();
  });
});

describe('StatusToasts markup', () => {
  test('an error toast has a dismiss button', () => {
    const html = renderToString(
      <StatusToasts error="Save failed" onClearError={() => undefined} onClearSuccess={() => undefined} />,
    );

    expect(html).toContain('class="toast-stack"');
    expect(html).toContain('role="alert"');
    expect(html).toContain('aria-label="Dismiss error notification"');
  });
});

describe('toast styles on a phone, issue 956', () => {
  const phone = styles.indexOf('@media (max-width: 767px) {', styles.indexOf('.toast__dismiss {'));

  test('the dismiss button is a 44px tap target', () => {
    const body = ruleBody('.toast__dismiss');
    expect(body).toContain('min-width: 44px');
    expect(body).toContain('min-height: 44px');
  });

  test('empty parts of the stack let taps through to the page', () => {
    expect(ruleBody('.toast-stack')).toContain('pointer-events: none');
    expect(ruleBody('.toast')).toContain('pointer-events: auto');
  });

  test('while a dialog is open the toast moves off its header, where Save and close sit', () => {
    expect(phone).toBeGreaterThanOrEqual(0);
    const body = ruleBody('body:has(.modal-overlay) .toast-stack:not(.toast-stack--app)', phone);
    expect(body).toContain('top: auto');
    expect(body).toContain('bottom: 8px');
  });
});
