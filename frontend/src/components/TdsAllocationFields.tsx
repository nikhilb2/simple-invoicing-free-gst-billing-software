import { useEffect, useState } from 'react';
import api from '../api/client';
import type { OutstandingInvoice, PaymentInvoiceAllocation, TaxWithholdingSection, TdsSuggestion } from '../types/api';
import formatCurrency from '../utils/formatting';
import { deductionDate, isFullySettled, overSettlement, sectionOptionLabel } from '../utils/tds';

// Sections change rarely and are the same for every row on a date: fetch once per date.
const sectionsByDate = new Map<string, Promise<TaxWithholdingSection[]>>();

function loadSections(date: string): Promise<TaxWithholdingSection[]> {
  let pending = sectionsByDate.get(date);
  if (!pending) {
    pending = api
      .get<TaxWithholdingSection[]>('/tax-withholding-sections', { params: { kind: 'tds', date } })
      .then((res) => res.data)
      .catch((err) => {
        sectionsByDate.delete(date);
        throw err;
      });
    sectionsByDate.set(date, pending);
  }
  return pending;
}

interface TdsAllocationFieldsProps {
  allocation: PaymentInvoiceAllocation;
  invoice: OutstandingInvoice;
  /** The payment's date (any ISO prefix); the deduction date is the earlier of this and the invoice date. */
  paymentDate: string | undefined;
  currencyCode: string;
  idPrefix: string;
  onChange: (patch: Pick<PaymentInvoiceAllocation, 'tds_amount' | 'tds_section_id'>) => void;
}

export default function TdsAllocationFields({
  allocation,
  invoice,
  paymentDate,
  currencyCode,
  idPrefix,
  onChange,
}: TdsAllocationFieldsProps) {
  const tds = Number(allocation.tds_amount || 0);
  const [open, setOpen] = useState(tds > 0);
  const [sections, setSections] = useState<TaxWithholdingSection[]>([]);
  const [sectionError, setSectionError] = useState('');
  const [suggestion, setSuggestion] = useState<TdsSuggestion | null>(null);

  const date = deductionDate(invoice.invoice_date, paymentDate);
  const sectionId = allocation.tds_section_id ?? null;

  useEffect(() => {
    if (!open || !date) return;
    let cancelled = false;
    setSectionError('');
    loadSections(date)
      .then((list) => { if (!cancelled) setSections(list); })
      .catch(() => { if (!cancelled) setSectionError('Unable to load TDS sections'); });
    return () => { cancelled = true; };
  }, [open, date]);

  useEffect(() => {
    if (!open || !sectionId) {
      setSuggestion(null);
      return;
    }
    let cancelled = false;
    api
      .get<TdsSuggestion>('/tds/suggestion', {
        params: { invoice_id: invoice.id, section_id: sectionId, payment_date: (paymentDate || '').slice(0, 10) || undefined },
      })
      .then((res) => { if (!cancelled) setSuggestion(res.data); })
      .catch(() => { if (!cancelled) setSuggestion(null); });
    return () => { cancelled = true; };
  }, [open, sectionId, invoice.id, paymentDate]);

  if (!open) {
    return (
      <div style={{ marginLeft: '28px' }}>
        <button
          type="button"
          className="button button--ghost button--small"
          onClick={() => setOpen(true)}
        >
          + TDS deducted
        </button>
      </div>
    );
  }

  const cash = Number(allocation.allocated_amount || 0);
  const over = overSettlement(invoice.remaining_amount, cash, tds);
  const settled = isFullySettled(invoice.remaining_amount, cash, tds);

  return (
    <div className="stack" style={{ marginLeft: '28px', gap: '8px' }}>
      <div className="field">
        <label htmlFor={`${idPrefix}-tds-section`}>TDS section</label>
        <select
          id={`${idPrefix}-tds-section`}
          className="input"
          value={sectionId ?? ''}
          onChange={(event) => onChange({ tds_amount: tds, tds_section_id: event.target.value ? Number(event.target.value) : null })}
        >
          <option value="">Select section</option>
          {sections.map((section) => (
            <option key={section.id} value={section.id}>{sectionOptionLabel(section)}</option>
          ))}
        </select>
        {sectionError ? <p className="field-warning">{sectionError}</p> : null}
      </div>
      <div className="field">
        <label htmlFor={`${idPrefix}-tds-amount`}>TDS deducted</label>
        <input
          id={`${idPrefix}-tds-amount`}
          className="input"
          type="number"
          min="0"
          step="0.01"
          value={allocation.tds_amount || ''}
          onChange={(event) => onChange({ tds_amount: parseFloat(event.target.value) || 0, tds_section_id: sectionId })}
        />
      </div>
      {suggestion ? (
        <div className="stack" style={{ gap: '4px' }}>
          {suggestion.applies ? (
            <p className="muted-text" style={{ margin: 0 }}>
              Suggested {formatCurrency(suggestion.amount, currencyCode)} ({suggestion.rate}% of {formatCurrency(suggestion.base_amount, currencyCode)}){' '}
              <button
                type="button"
                className="button button--secondary button--small"
                onClick={() => onChange({ tds_amount: suggestion.amount, tds_section_id: sectionId })}
              >
                Use
              </button>
            </p>
          ) : null}
          {suggestion.reason ? <p className="muted-text" style={{ margin: 0 }}>{suggestion.reason}</p> : null}
        </div>
      ) : null}
      {over > 0 ? (
        <p className="field-warning">Cash and TDS exceed what is remaining on this invoice by {formatCurrency(over, currencyCode)}.</p>
      ) : settled ? (
        <p className="table-subtext" style={{ margin: 0 }}>Fully settled (cash + TDS)</p>
      ) : null}
      <div>
        <button
          type="button"
          className="button button--ghost button--small"
          onClick={() => { onChange({ tds_amount: 0, tds_section_id: null }); setOpen(false); }}
        >
          Remove TDS
        </button>
      </div>
    </div>
  );
}
