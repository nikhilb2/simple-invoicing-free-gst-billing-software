import { useCallback, useEffect, useRef, useState } from 'react';

/** Messages for the fields that failed the last save, keyed by the field's id. */
export type FieldErrors = Record<string, string>;

type Control = HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement;

type ValidityFacts = Pick<ValidityState, 'customError' | 'valueMissing' | 'rangeUnderflow' | 'rangeOverflow' | 'stepMismatch' | 'badInput'>;

/** A short message for a failed field. The browser's own wording is long for a narrow column. */
export function fieldErrorMessage(
  validity: ValidityFacts,
  field: { validationMessage: string; min?: string; max?: string; step?: string },
): string {
  if (validity.customError) return field.validationMessage;
  if (validity.valueMissing) return 'Required';
  if (validity.badInput) return 'Enter a number';
  if (validity.rangeUnderflow && field.min) return `Must be at least ${field.min}`;
  if (validity.rangeOverflow && field.max) return `Must be at most ${field.max}`;
  if (validity.stepMismatch && field.step === '1') return 'Use a whole number';
  return field.validationMessage;
}

function messageFor(el: Control): string {
  return fieldErrorMessage(el.validity, {
    validationMessage: el.validationMessage,
    min: 'min' in el ? el.min : undefined,
    max: 'max' in el ? el.max : undefined,
    step: 'step' in el ? el.step : undefined,
  });
}

function markInvalid(el: Control) {
  el.setAttribute('aria-invalid', 'true');
  if (el.id && !el.hasAttribute('aria-describedby')) {
    el.setAttribute('aria-describedby', `${el.id}-error`);
    el.dataset.errorDescribed = 'true';
  }
}

function clearMark(el: Element | null) {
  if (!el) return;
  el.removeAttribute('aria-invalid');
  if (el instanceof HTMLElement && el.dataset.errorDescribed) {
    el.removeAttribute('aria-describedby');
    delete el.dataset.errorDescribed;
  }
}

/**
 * Keeps a form's Save button enabled and tells the user what is missing when
 * they press it. A disabled button does not say which field holds it back.
 *
 * The browser still checks `required`, `min` and custom validity on submit.
 * Each field that fails is outlined (aria-invalid) and its message is kept
 * under its id, for a <FieldError> beside it. The first one is scrolled to and
 * focused (a combobox is only scrolled to: focus would open its list over the
 * message). A field's mark goes as soon as it becomes valid.
 *
 * Put `onInvalidCapture` on the <form>. Pass `revealFirst: false` when the form
 * scrolls to its first problem itself (the invoice composer, whose problems
 * include more than its fields). A form that calls `checkValidity()` itself
 * can call `flush()` right after it, so the marks land in the same render as
 * its own state.
 */
export function useFormFieldErrors({ revealFirst = true }: { revealFirst?: boolean } = {}) {
  const [errors, setErrors] = useState<FieldErrors>({});
  const pending = useRef<Control[] | null>(null);
  const marked = useRef<Set<Control>>(new Set());

  const flush = useCallback(() => {
    const failed = pending.current;
    if (failed === null) return;
    pending.current = null;
    marked.current.forEach((el) => { if (!failed.includes(el)) clearMark(el); });
    marked.current = new Set(failed);
    const next: FieldErrors = {};
    failed.forEach((el) => {
      markInvalid(el);
      if (el.id) next[el.id] = messageFor(el);
    });
    setErrors(next);
    const first = failed[0];
    if (first && revealFirst) {
      first.scrollIntoView({ block: 'center', behavior: 'smooth' });
      // A combobox opens its list on focus, and the list would cover the message.
      // One with nothing to list (data-focus-on-error) has no list to cover it.
      if (first.getAttribute('role') !== 'combobox' || first.dataset.focusOnError) first.focus({ preventScroll: true });
    }
  }, [revealFirst]);

  /* The browser fires one `invalid` per failing field, each as its own event,
     so a microtask would flush after the first. A timeout waits for them all. */
  const onInvalidCapture = useCallback((event: React.FormEvent<HTMLFormElement>) => {
    // Our message beside the field replaces the browser's bubble.
    event.preventDefault();
    if (pending.current === null) {
      pending.current = [];
      window.setTimeout(flush, 0);
    }
    pending.current.push(event.target as Control);
  }, [flush]);

  /* Re-check after every render: the fields' values live in the parent's state,
     and child effects (which set custom validity) have already run by now. */
  useEffect(() => {
    if (marked.current.size === 0) return;
    const stillInvalid = new Set<Control>();
    marked.current.forEach((el) => {
      if (el.isConnected && !el.disabled && !el.validity.valid) stillInvalid.add(el);
      else clearMark(el);
    });
    if (stillInvalid.size === marked.current.size) return;
    marked.current = stillInvalid;
    setErrors((current) => {
      const next: FieldErrors = {};
      stillInvalid.forEach((el) => { if (el.id && current[el.id]) next[el.id] = messageFor(el); });
      return next;
    });
  });

  return { errors, onInvalidCapture, flush };
}

/**
 * The message under a field that failed the last save. `label` names the field
 * when the message sits apart from it; `text` words it in place of the browser.
 */
export function FieldError({ id, errors, label, text, className }: { id: string; errors: FieldErrors; label?: string; text?: string | null; className?: string }) {
  const message = errors[id] ? text || errors[id] : '';
  if (!message) return null;
  return (
    <small id={`${id}-error`} className={className ? `field-error field-error--block ${className}` : 'field-error field-error--block'} role="alert">
      {label ? `${label}: ${message}` : message}
    </small>
  );
}

/**
 * The messages for one invoice line, as a full-width row under its fields.
 * Inside the field cells they would make one cell taller than the rest and
 * push its control out of line with its neighbours.
 */
export function LineFieldErrors({ fields, errors }: { fields: { id: string; label: string }[]; errors: FieldErrors }) {
  if (!fields.some((field) => errors[field.id])) return null;
  return (
    <div className="line-item__errors">
      {fields.map((field) => <FieldError key={field.id} id={field.id} label={field.label} errors={errors} />)}
    </div>
  );
}
