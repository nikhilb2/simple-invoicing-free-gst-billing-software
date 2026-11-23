import { useEffect, useRef } from 'react';

type ToastKind = 'success' | 'error';

type ToastProps = {
  kind: ToastKind;
  message: string;
  onDismiss: () => void;
};

type StatusToastsProps = {
  error?: string;
  success?: string;
  onClearError: () => void;
  onClearSuccess: () => void;
  successDurationMs?: number;
  /** Errors stay longer than successes so they can be read, but they do clear. */
  errorDurationMs?: number;
};

function Toast({ kind, message, onDismiss }: ToastProps) {
  const title = kind === 'success' ? 'Success notification' : 'Error notification';

  return (
    <div className={`toast toast--${kind}`} role={kind === 'error' ? 'alert' : 'status'} aria-live={kind === 'error' ? 'assertive' : 'polite'}>
      <div className="toast__content">
        <strong className="toast__title">{title}</strong>
        <span className="toast__message">{message}</span>
      </div>
      <button
        type="button"
        className="toast__dismiss"
        onClick={onDismiss}
        aria-label={`Dismiss ${kind} notification`}
        title="Dismiss notification"
      >
        ×
      </button>
    </div>
  );
}

export default function StatusToasts({
  error,
  success,
  onClearError,
  onClearSuccess,
  successDurationMs = 5000,
  errorDurationMs = 8000,
}: StatusToastsProps) {
  // Callers often pass inline arrows. Reading them through refs keeps a parent re-render
  // (every keystroke in a form) from restarting the countdown.
  const onClearErrorRef = useRef(onClearError);
  const onClearSuccessRef = useRef(onClearSuccess);
  useEffect(() => {
    onClearErrorRef.current = onClearError;
    onClearSuccessRef.current = onClearSuccess;
  });

  useEffect(() => {
    if (!success) {
      return undefined;
    }

    const timeoutId = window.setTimeout(() => {
      onClearSuccessRef.current();
    }, successDurationMs);

    return () => window.clearTimeout(timeoutId);
  }, [success, successDurationMs]);

  useEffect(() => {
    if (!error) {
      return undefined;
    }

    const timeoutId = window.setTimeout(() => {
      onClearErrorRef.current();
    }, errorDurationMs);

    return () => window.clearTimeout(timeoutId);
  }, [error, errorDurationMs]);

  // An error that was already showing belongs to an earlier action, so a new success replaces
  // it instead of stacking beside it. An error that arrives together with the success stays.
  const errorBeforeRender = useRef(false);
  useEffect(() => {
    if (success && errorBeforeRender.current) {
      onClearError();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only a newly shown success should clear
  }, [success]);
  useEffect(() => {
    errorBeforeRender.current = Boolean(error);
  });

  if (!error && !success) {
    return null;
  }

  return (
    <div className="toast-stack" aria-live="polite" aria-atomic="true">
      {error ? <Toast kind="error" message={error} onDismiss={onClearError} /> : null}
      {success ? <Toast kind="success" message={success} onDismiss={onClearSuccess} /> : null}
    </div>
  );
}
