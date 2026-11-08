import type { Ledger, TaxWithholdingSection } from '../../../types/api';
import formatCurrency from '../../../utils/formatting';
import { tcsLabel } from '../../../utils/tcs';
import { sectionOptionLabels } from '../../../utils/withholdingSections';
import { EMPTY_TCS_FORM, effectiveTcsRate, tcsHints, tcsRateInputValue, type TcsFormState } from '../tcsForm';

type TcsFieldsProps = {
  idPrefix: string;
  form: TcsFormState;
  onChange: (next: TcsFormState) => void;
  sections: TaxWithholdingSection[] | undefined;
  section: TaxWithholdingSection | null;
  buyer: Partial<Ledger> | null | undefined;
  /** The worked-out amount from computeInvoiceTotals, shown until the user types over it. */
  previewAmount: number | undefined;
  currencyCode: string;
  notice?: string;
  /** The document total including TCS, shown beside the TCS line when given. */
  totalAmount?: number;
};

/** Section, rate and amount for TCS (#769): the app suggests the rate, the user decides. */
export default function TcsFields({
  idPrefix, form, onChange, sections, section, buyer, previewAmount, currencyCode, notice, totalAmount,
}: TcsFieldsProps) {
  const sectionLabels = sectionOptionLabels(sections ?? []);
  return (
    <div className="stack" style={{ gap: '8px', gridColumn: '1 / -1' }} data-testid="tcs-fields">
      <div className="field" style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: 0, flexWrap: 'wrap' }}>
        <label htmlFor={`${idPrefix}-tcs-section`} style={{ marginBottom: 0, fontSize: '13px' }}>TCS:</label>
        <select
          id={`${idPrefix}-tcs-section`}
          className="input"
          value={form.sectionId}
          onChange={(event) => onChange({ ...EMPTY_TCS_FORM, sectionId: event.target.value })}
          style={{ maxWidth: '360px' }}
        >
          <option value="">No TCS</option>
          {(sections ?? []).map((entry) => (
            <option key={entry.id} value={entry.id}>{sectionLabels.get(entry.id)}</option>
          ))}
        </select>
        {section ? (
          <>
            <label htmlFor={`${idPrefix}-tcs-rate`} style={{ marginBottom: 0, fontSize: '13px' }}>Rate %</label>
            <input
              id={`${idPrefix}-tcs-rate`}
              className="input"
              type="number"
              step="0.001"
              min="0"
              value={tcsRateInputValue(form, section, buyer)}
              onChange={(event) => onChange({ ...form, rateText: event.target.value })}
              style={{ width: '90px' }}
            />
            <label htmlFor={`${idPrefix}-tcs-amount`} style={{ marginBottom: 0, fontSize: '13px' }}>Amount</label>
            <input
              id={`${idPrefix}-tcs-amount`}
              className="input"
              type="number"
              step="0.01"
              min="0"
              value={form.amountText ?? String(previewAmount ?? 0)}
              onChange={(event) => onChange({ ...form, amountText: event.target.value === '' ? null : event.target.value })}
              style={{ width: '120px' }}
            />
            {form.amountText !== null || form.rateText !== null ? (
              <button type="button" className="button button--ghost" onClick={() => onChange({ ...form, rateText: null, amountText: null })}>
                Reset
              </button>
            ) : null}
          </>
        ) : null}
      </div>
      {notice ? <p className="muted-text" role="status" style={{ marginTop: 0 }}>{notice}</p> : null}
      {tcsHints(section, buyer).map((hint) => (
        <p key={hint} className="muted-text" style={{ marginTop: 0 }}>{hint}</p>
      ))}
      {section ? (
        <p className="muted-text" style={{ marginTop: 0 }}>
          {tcsLabel(effectiveTcsRate(form, section, buyer), section.section_ref)}: {formatCurrency(previewAmount ?? 0, currencyCode)}
          {totalAmount !== undefined ? ` · Total: ${formatCurrency(totalAmount, currencyCode)}` : null}
        </p>
      ) : null}
    </div>
  );
}
