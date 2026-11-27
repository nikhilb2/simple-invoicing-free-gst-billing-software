import { useEffect, useRef, type ReactNode } from 'react';
import { Plus } from 'lucide-react';
import { Link } from 'react-router-dom';

/** Under the dropdown after "Change" on a first run. */
export const BILL_TYPE_HINT = 'Purchase: a bill you got from a supplier. Quotation and proforma: offers, not bills.';
export const FIRST_ITEM_HINT = 'Name, price and GST %. It goes on this bill and is saved for next time.';
export const FIRST_CUSTOMER_TEXT = 'Only the name is needed. Phone, address and GSTIN can come later.';

/** First run: one document type, with a quiet way to pick another (#1134). */
export function BillTypeRow({ onChange }: { onChange: () => void }) {
  return (
    <div className="field" data-testid="invoice-bill-type-row">
      <span className="bill-type-row__label" id="invoice-bill-type-label">Bill type</span>
      <div className="bill-type-row__line">
        <strong className="bill-type-row__value">Sales invoice</strong>
        <button type="button" className="link-button link-button--tap" aria-describedby="invoice-bill-type-label" onClick={onChange}>
          Change
        </button>
      </div>
    </div>
  );
}

/**
 * Today's Voucher type dropdown. After "Change" on a first run it takes focus
 * and says what the other types are (`afterChange`).
 */
export function VoucherTypeSelect({
  afterChange,
  children,
  ...select
}: {
  afterChange: boolean;
  children: ReactNode;
  value: string;
  disabled: boolean;
  onChange: (value: string) => void;
}) {
  const ref = useRef<HTMLSelectElement>(null);
  useEffect(() => {
    if (afterChange) ref.current?.focus();
  }, [afterChange]);
  return (
    <div className="field">
      <label htmlFor="invoice-voucher-type">{afterChange ? 'Bill type' : 'Voucher type'}</label>
      <select
        ref={ref}
        id="invoice-voucher-type"
        className="select"
        value={select.value}
        disabled={select.disabled}
        aria-describedby={afterChange ? 'invoice-voucher-type-hint' : undefined}
        onChange={(event) => select.onChange(event.target.value)}
      >
        {children}
      </select>
      {afterChange ? <p className="field-hint" id="invoice-voucher-type-hint">{BILL_TYPE_HINT}</p> : null}
    </div>
  );
}

/** Line 1 in a company with no products: the item is added right here. */
export function FirstItemButton({ id, onClick }: { id: string; onClick: () => void }) {
  return (
    <>
      <button
        type="button"
        id={id}
        className="button button--ghost first-item-button"
        data-tour="add-product"
        aria-describedby={`${id}-hint`}
        onClick={onClick}
      >
        <Plus size={14} aria-hidden="true" />
        Add your first item
      </button>
      <p className="field-hint" id={`${id}-hint`}>{FIRST_ITEM_HINT}</p>
    </>
  );
}

/** Under Customer, only while there is no customer. The first item is added on Line 1. */
export function FirstCustomerBox({ onAdd }: { onAdd: () => void }) {
  return (
    <div className="empty-state stack composer-first-run" data-testid="invoice-first-run">
      <strong>Add your first customer</strong>
      <p className="muted-text" style={{ margin: 0 }}>{FIRST_CUSTOMER_TEXT}</p>
      <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
        <button type="button" className="button button--primary" data-tour="add-customer" onClick={onAdd}>
          <Plus size={13} />
          Add a customer
        </button>
      </div>
    </div>
  );
}

/** On Quotations, until the company has an invoice. */
export function QuotationsFirstRunNote() {
  return (
    <div className="marketplace-note marketplace-note--emphasis in-app-notice quotations-first-run" data-testid="quotations-first-run-note">
      <strong className="in-app-notice__title">A quotation is an offer, not a bill.</strong>
      <span>It doesn&apos;t count in your sales or GST. To bill a customer now, make an invoice.</span>
      <Link to="/invoices" className="button button--ghost button--small in-app-notice__copy quotations-first-run__link">
        New invoice
      </Link>
    </div>
  );
}
