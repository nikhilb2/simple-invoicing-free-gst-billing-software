import { useEffect, useRef, type FormEvent, type Ref } from 'react';
import BillHeaderPreview from './BillHeaderPreview';
import GstinInput from './GstinInput';
import { busyClass } from '../utils/saveFeedback';
import { keepInViewScroll, visibleViewportBottom } from '../utils/keepInView';

export const SETUP_NAME_HINT = 'Top of your bills. You can change it later.';
export const SETUP_GSTIN_HINT = '15 characters, e.g. 27ABCDE1234F1Z0. Leave it blank if you are not registered.';

type Props = {
  /** True until the profile request answers: the hero shows, the card waits. */
  loading?: boolean;
  name: string;
  onNameChange: (name: string) => void;
  /** "Enter your business name." after an empty Start billing. */
  nameError?: string;
  gst: string;
  onGstChange: (gst: string) => void;
  onGstBlur?: () => void;
  gstError?: string | null;
  /** The GSTIN field replaces "Have a GSTIN? Add it" once tapped. */
  gstOpen: boolean;
  onOpenGst: () => void;
  /** Waiting on the server: "Starting…", and nothing can be changed. */
  busy: boolean;
  /** A failed save, under the button. The typed values stay. */
  saveError?: string;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  nameInputRef?: Ref<HTMLInputElement>;
  gstInputRef?: Ref<HTMLInputElement>;
};

/**
 * "Add your business", the first-run screen (#963 addendum, #1097).
 *
 * One field, prefilled with the account's name, a one-row sketch of the bill
 * header under it, GSTIN behind a link, and "Start billing" directly below so it
 * stays above a phone keyboard. No address, no required-field legend, no footer
 * bar: everything else is asked for later.
 */
export default function FirstBusinessSetup({
  loading = false,
  name,
  onNameChange,
  nameError,
  gst,
  onGstChange,
  onGstBlur,
  gstError,
  gstOpen,
  onOpenGst,
  busy,
  saveError,
  onSubmit,
  nameInputRef,
  gstInputRef,
}: Props) {
  const formRef = useRef<HTMLFormElement>(null);
  const submitRef = useRef<HTMLButtonElement>(null);

  // While a field here is focused on a phone, keep "Start billing" above the
  // keyboard. With GSTIN open the button sits below a 336px keyboard on a
  // 390×844 phone, so scroll the page up just enough (never hiding the field).
  useEffect(() => {
    const form = formRef.current;
    if (!form || typeof window === 'undefined') return undefined;
    let timer: number | undefined;
    const adjust = () => {
      const focused = document.activeElement;
      const button = submitRef.current;
      if (!button || !(focused instanceof HTMLElement) || !form.contains(focused) || focused === button) return;
      const delta = keepInViewScroll({
        targetBottom: button.getBoundingClientRect().bottom,
        viewportBottom: visibleViewportBottom(),
        focusedTop: focused.getBoundingClientRect().top,
      });
      if (delta > 0) window.scrollBy(0, delta);
    };
    // The keyboard slides in after focus; check again once it has.
    const onFocusIn = () => {
      window.clearTimeout(timer);
      adjust();
      timer = window.setTimeout(adjust, 350);
    };
    form.addEventListener('focusin', onFocusIn);
    window.visualViewport?.addEventListener('resize', adjust);
    return () => {
      window.clearTimeout(timer);
      form.removeEventListener('focusin', onFocusIn);
      window.visualViewport?.removeEventListener('resize', adjust);
    };
  }, [loading]);

  return (
    <div className="page-grid company-setup-page">
      <section className="page-hero">
        <div>
          <p className="eyebrow">Getting started</p>
          <h1 className="page-title">Add your business</h1>
          <p className="section-copy">One detail and you can make your first bill.</p>
        </div>
      </section>

      {loading ? (
        <div className="empty-state">Loading company profile...</div>
      ) : (
        <article className="panel company-setup">
          {/* noValidate: the empty name is answered under the field, not by a browser bubble. */}
          <form ref={formRef} className="stack" onSubmit={onSubmit} noValidate>
            <div className="field">
              <label htmlFor="company-name">Business name</label>
              <input
                id="company-name"
                ref={nameInputRef}
                className="input"
                value={name}
                onChange={(event) => onNameChange(event.target.value)}
                autoComplete="organization"
                placeholder="e.g. Sharma General Store"
                readOnly={busy}
                aria-invalid={nameError ? true : undefined}
                aria-describedby={nameError ? 'company-name-error' : 'company-name-hint'}
              />
              <div className="company-setup__preview">
                <BillHeaderPreview name={name} />
                {/* The error takes the hint's place, in a slot of fixed height, so nothing below moves. */}
                <div className="company-setup__hint-slot">
                  {nameError ? (
                    <p className="field-error" id="company-name-error" role="alert">{nameError}</p>
                  ) : (
                    <small className="field-hint" id="company-name-hint">{SETUP_NAME_HINT}</small>
                  )}
                </div>
              </div>
            </div>

            {gstOpen ? (
              <div className="field">
                <label htmlFor="company-gst">GSTIN (optional)</label>
                <GstinInput
                  id="company-gst"
                  ref={gstInputRef}
                  className="input"
                  value={gst}
                  onValueChange={onGstChange}
                  onBlur={onGstBlur}
                  autoCapitalize="characters"
                  readOnly={busy}
                  aria-invalid={gstError ? true : undefined}
                  aria-describedby={gstError ? 'company-gst-hint company-gst-error' : 'company-gst-hint'}
                />
                <small className="field-hint" id="company-gst-hint">{SETUP_GSTIN_HINT}</small>
                {gstError ? <p className="field-error" id="company-gst-error" role="alert">{gstError}</p> : null}
              </div>
            ) : (
              <button
                type="button"
                className="link-button link-button--tap company-setup__gst-link"
                onClick={onOpenGst}
                disabled={busy}
              >
                Have a GSTIN? Add it
              </button>
            )}

            <button
              ref={submitRef}
              type="submit"
              className={`button button--primary company-setup__submit${busyClass(busy)}`}
              disabled={busy}
              aria-busy={busy || undefined}
              aria-describedby={saveError ? 'company-setup-save-error' : undefined}
            >
              {busy ? 'Starting…' : 'Start billing'}
            </button>
            {saveError ? (
              <p className="field-error company-setup__save-error" id="company-setup-save-error" role="alert">{saveError}</p>
            ) : null}
          </form>
        </article>
      )}
    </div>
  );
}
