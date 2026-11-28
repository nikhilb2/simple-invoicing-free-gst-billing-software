import { useState } from 'react';
import { GST_SLABS, GST_ZERO_NOTE, isGstSlab } from './productFormRules';

const OTHER_GST_VALUE = '__other__';

type GstRateSelectProps = {
  /** Id of the select; the note and the "other rate" input derive theirs from it. */
  id: string;
  /** The rate as a string, '' while none has been chosen. */
  value: string;
  onChange: (rate: string) => void;
  /** A message for a save refused because no rate was chosen, shown above the hint. */
  error?: string;
};

/**
 * The required GST rate dropdown shared by the catalogue form and the invoice
 * composer's quick-add. It starts empty on purpose, so a rate is always a choice;
 * "Other rate…" reveals a number input for rates outside the usual slabs.
 */
export default function GstRateSelect({ id, value, onChange, error }: GstRateSelectProps) {
  const [other, setOther] = useState(() => value !== '' && !isGstSlab(value));
  const selectValue = value === '' && !other ? '' : other || !isGstSlab(value) ? OTHER_GST_VALUE : String(Number(value));
  const isZero = value !== '' && Number(value) === 0;
  const noteId = `${id}-note`;
  const errorId = `${id}-error`;

  return (
    <>
      <select
        id={id}
        className="select"
        value={selectValue}
        required
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${noteId} ${errorId}` : noteId}
        onChange={(e) => {
          if (e.target.value === OTHER_GST_VALUE) {
            setOther(true);
            return;
          }
          setOther(false);
          onChange(e.target.value);
        }}
      >
        <option value="" disabled>
          Choose a rate
        </option>
        {GST_SLABS.map((slab) => (
          <option key={slab} value={slab}>
            {slab === 0 ? '0% (no GST)' : `${slab}%`}
          </option>
        ))}
        <option value={OTHER_GST_VALUE}>Other rate…</option>
      </select>
      {selectValue === OTHER_GST_VALUE ? (
        <input
          id={`${id}-other`}
          className="input"
          type="number"
          step="0.01"
          min="0"
          max="100"
          aria-label="GST rate in percent"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          required
        />
      ) : null}
      {error ? (
        <p className="field-error field-error--block" id={errorId} role="alert">
          {error}
        </p>
      ) : null}
      <p className="field-hint" id={noteId} data-testid={noteId} role={isZero ? 'status' : undefined}>
        {isZero ? GST_ZERO_NOTE : 'The tax you charge customers on this product.'}
      </p>
    </>
  );
}
