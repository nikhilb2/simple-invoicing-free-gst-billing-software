// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import StatusToasts from './StatusToasts';

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe('StatusToasts', () => {
  test('an error toast clears itself after the default 8 seconds, later than a success would', () => {
    const onClearError = vi.fn();
    render(<StatusToasts error="Save failed" onClearError={onClearError} onClearSuccess={() => undefined} />);

    act(() => {
      vi.advanceTimersByTime(7999);
    });
    expect(onClearError).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(onClearError).toHaveBeenCalledTimes(1);
  });

  test('errorDurationMs overrides the error timeout', () => {
    const onClearError = vi.fn();
    render(<StatusToasts error="Save failed" errorDurationMs={1000} onClearError={onClearError} onClearSuccess={() => undefined} />);

    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(onClearError).toHaveBeenCalledTimes(1);
  });

  test('a success toast still clears after 5 seconds', () => {
    const onClearSuccess = vi.fn();
    render(<StatusToasts success="Saved" onClearError={() => undefined} onClearSuccess={onClearSuccess} />);

    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(onClearSuccess).toHaveBeenCalledTimes(1);
  });

  test('a parent re-render with a fresh callback does not restart the countdown', () => {
    const first = vi.fn();
    const second = vi.fn();
    const { rerender } = render(<StatusToasts error="Save failed" onClearError={first} onClearSuccess={() => undefined} />);

    act(() => {
      vi.advanceTimersByTime(6000);
    });
    rerender(<StatusToasts error="Save failed" onClearError={second} onClearSuccess={() => undefined} />);
    act(() => {
      vi.advanceTimersByTime(2000);
    });

    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledTimes(1);
  });

  test('a new success clears an error that was already showing', () => {
    const onClearError = vi.fn();
    const { rerender } = render(<StatusToasts error="Save failed" onClearError={onClearError} onClearSuccess={() => undefined} />);

    rerender(<StatusToasts error="Save failed" success="Saved" onClearError={onClearError} onClearSuccess={() => undefined} />);
    expect(onClearError).toHaveBeenCalledTimes(1);
  });

  test('the dismiss button clears the error', () => {
    const onClearError = vi.fn();
    render(<StatusToasts error="Save failed" onClearError={onClearError} onClearSuccess={() => undefined} />);

    fireEvent.click(screen.getByRole('button', { name: 'Dismiss error notification' }));
    expect(onClearError).toHaveBeenCalledTimes(1);
  });
});
