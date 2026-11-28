import type { ReactNode } from 'react';
import type { DiscountMode } from '../../../types/api';
import formatCurrency from '../../../utils/formatting';
import { BILL_DISCOUNT_ID, signedCurrency } from '../composerTotalsText';

export type ComposerTotalsDiscount = {
  /** The amount box and its % / Flat choice are showing (a value, or "+ Add discount" tapped). */
  open: boolean;
  type: 'percentage' | 'net';
  value: string;
  /** What comes off, already worked out. */
  amount: number;
  /** The value can't be used: the row shows "—" and the rest is worked out without it. */
  invalid: boolean;
  /** The browser's custom validity for the box, so a save is refused for it. Empty when fine. */
  validity: string;
  /** The message under the box after a refused save (a <FieldError>). */
  error?: ReactNode;
  onOpen: () => void;
  onTypeChange: (type: 'percentage' | 'net') => void;
  onValueChange: (value: string) => void;
  /** Set to the amount box while it shows, to focus it after "+ Add discount" on desktop. */
  inputRef?: { current: HTMLInputElement | null };
};

export type ComposerTotalsProps = {
  /** Which way the document takes its bill discount, and so the order of the rows. */
  mode: DiscountMode;
  currencyCode: string;
  subtotal: number;
  discount: ComposerTotalsDiscount;
  taxableAmount: number;
  gstRows: { label: string; amount: number }[];
  tcs?: { label: string; amount: number } | null;
  /** Null when round off is not ticked. */
  roundOff?: number | null;
  total: number;
  hint?: string | null;
  note?: { text: string; action?: { label: string; onClick: () => void } } | null;
};

function Row({ label, value, variant }: { label: ReactNode; value: string; variant?: 'muted' | 'total' }) {
  return (
    <div className={variant ? `composer-totals__row composer-totals__row--${variant}` : 'composer-totals__row'}>
      <span>{label}</span>
      <span className="composer-totals__value">{value}</span>
    </div>
  );
}

function DiscountRow({ discount, currencyCode }: { discount: ComposerTotalsDiscount; currencyCode: string }) {
  if (!discount.open) {
    return (
      <div className="composer-totals__row composer-totals__row--add">
        <span>Discount</span>
        <button type="button" className="link-button link-button--tap" onClick={discount.onOpen}>+ Add discount</button>
      </div>
    );
  }
  const percentage = discount.type === 'percentage';
  const label = percentage && discount.value.trim() !== '' ? `Discount (${discount.value.trim()}%)` : 'Discount';
  const value = discount.invalid ? '—' : discount.amount > 0 ? signedCurrency(-discount.amount, currencyCode) : formatCurrency(0, currencyCode);
  return (
    <div className="composer-totals__discount">
      <div className="composer-totals__row">
        <label htmlFor={BILL_DISCOUNT_ID}>{label}</label>
        <span className="composer-totals__value">{value}</span>
      </div>
      <div className="composer-totals__discount-controls">
        <input
          id={BILL_DISCOUNT_ID}
          ref={(input) => {
            input?.setCustomValidity(discount.validity);
            if (discount.inputRef) discount.inputRef.current = input;
          }}
          className="input"
          type="text"
          inputMode="decimal"
          autoComplete="off"
          value={discount.value}
          onChange={(event) => discount.onValueChange(event.target.value)}
          placeholder={percentage ? 'e.g. 5' : 'e.g. 100.00'}
        />
        <div className="line-item__discount-modes">
          <input
            id={`${BILL_DISCOUNT_ID}-pct`}
            type="radio"
            name={`${BILL_DISCOUNT_ID}-type`}
            value="percentage"
            checked={percentage}
            onChange={() => discount.onTypeChange('percentage')}
          />
          <label htmlFor={`${BILL_DISCOUNT_ID}-pct`}>%</label>
          <input
            id={`${BILL_DISCOUNT_ID}-net`}
            type="radio"
            name={`${BILL_DISCOUNT_ID}-type`}
            value="net"
            checked={!percentage}
            onChange={() => discount.onTypeChange('net')}
          />
          <label htmlFor={`${BILL_DISCOUNT_ID}-net`}>Flat</label>
        </div>
      </div>
      {discount.error}
    </div>
  );
}

/**
 * The bill's totals under the line items (#1154), with the bill discount in it.
 * Before GST (every new document): Subtotal, Discount, Taxable value, GST, then
 * TCS, Round off and Total. A document saved with the discount after GST keeps
 * its own order: Taxable value, GST, Discount, and the rest.
 */
export default function ComposerTotals({
  mode, currencyCode, subtotal, discount, taxableAmount, gstRows, tcs, roundOff, total, hint, note,
}: ComposerTotalsProps) {
  const money = (value: number) => signedCurrency(value, currencyCode);
  const gst = gstRows.map((row) => <Row key={row.label} label={row.label} value={money(row.amount)} variant="muted" />);
  const showSubtotal = discount.open && discount.value.trim() !== '';
  return (
    <section className="composer-totals" aria-label="Bill totals" data-testid="composer-totals">
      {note ? (
        <div className="composer-totals__note">
          <p>{note.text}</p>
          {note.action ? (
            <button type="button" className="link-button link-button--tap" onClick={note.action.onClick}>{note.action.label}</button>
          ) : null}
        </div>
      ) : null}
      {mode === 'after_tax' ? (
        <>
          <Row label="Taxable value" value={money(taxableAmount)} />
          {gst}
          <DiscountRow discount={discount} currencyCode={currencyCode} />
        </>
      ) : (
        <>
          {showSubtotal ? <Row label="Subtotal" value={money(subtotal)} /> : null}
          <DiscountRow discount={discount} currencyCode={currencyCode} />
          <Row label="Taxable value" value={money(taxableAmount)} />
          {gst}
        </>
      )}
      {tcs ? <Row label={tcs.label} value={money(tcs.amount)} variant="muted" /> : null}
      {roundOff != null ? <Row label="Round off" value={money(roundOff)} variant="muted" /> : null}
      <Row label="Total" value={money(total)} variant="total" />
      {hint ? <p className="field-hint composer-totals__hint">{hint}</p> : null}
    </section>
  );
}
