import { PRICE_INCLUDES_GST_LABEL } from '../utils/invoiceTotals';

type TaxInclusiveToggleProps = {
  id: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  /** Worked example from `priceIncludesGstExample`; null hides it. */
  example: string | null;
};

/** "Price already includes GST" checkbox shared by the invoice composer and the quick-create modal. */
export default function TaxInclusiveToggle({ id, checked, onChange, example }: TaxInclusiveToggleProps) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <label className="inline-check" htmlFor={id}>
        <input
          id={id}
          type="checkbox"
          checked={checked}
          aria-describedby={`${id}-hint`}
          onChange={(event) => onChange(event.target.checked)}
        />
        {PRICE_INCLUDES_GST_LABEL}
      </label>
      <small id={`${id}-hint`} className="field-hint">
        {example ?? 'Tick this if the prices you type already include GST.'}
      </small>
    </div>
  );
}
