import { FileText, Plus } from 'lucide-react';
import EmptyState from '../../components/EmptyState';
import LoadingState from '../../components/LoadingState';
import Pagination from '../../components/Pagination';
import type { CreditNote, CreditNoteType, Invoice, Ledger } from '../../types/api';
import formatCurrency, { formatDate } from '../../utils/formatting';
import { creditNoteInvoiceLabels } from '../../utils/creditNoteInvoices';
import { deepLinkClass } from '../../utils/deepLink';

const typeLabels: Record<CreditNoteType, string> = {
  return: 'Return',
  discount: 'Discount',
  adjustment: 'Adjustment',
};

export const EMPTY_NO_NOTES = 'No credit notes yet. Make one when a customer sends goods back or you give a discount after billing.';
export const EMPTY_FILTERED = 'Nothing matches these filters. Try a different status or search.';

type CreditNotesListProps = {
  notes: CreditNote[];
  ledgers: Pick<Ledger, 'id' | 'name'>[];
  invoices: Pick<Invoice, 'id' | 'invoice_number'>[];
  currencyCode: string;
  highlightId: number | null;
  loading: boolean;
  hasFilters: boolean;
  page: number;
  totalPages: number;
  total: number;
  pageSize: number;
  onPageChange: (page: number) => void;
  onView: (note: CreditNote) => void;
  onNew: () => void;
};

function StatusChip({ status }: { status: string }) {
  return status === 'cancelled'
    ? <span className="status-chip status-chip--cancelled">Cancelled</span>
    : <span className="status-chip status-chip--success">Active</span>;
}

/** The list half of the Credit / Debit Notes page: table on desktop, cards on a phone. */
export default function CreditNotesList({
  notes,
  ledgers,
  invoices,
  currencyCode,
  highlightId,
  loading,
  hasFilters,
  page,
  totalPages,
  total,
  pageSize,
  onPageChange,
  onView,
  onNew,
}: CreditNotesListProps) {
  const customerName = (note: CreditNote) => ledgers.find((entry) => entry.id === note.ledger_id)?.name || `Customer #${note.ledger_id}`;
  const voucher = (note: CreditNote) => (note.direction === 'inward' ? 'Purchase' : 'Sales');

  return (
    <>
      {loading && notes.length === 0 ? <LoadingState message="Loading credit notes..." /> : null}

      {!loading && notes.length === 0 ? (
        <EmptyState
          message={hasFilters ? EMPTY_FILTERED : EMPTY_NO_NOTES}
          action={hasFilters ? undefined : (
            <button type="button" className="button button--primary" onClick={onNew}>
              <Plus size={14} aria-hidden="true" /> New credit note
            </button>
          )}
        />
      ) : null}

      {notes.length > 0 ? (
        <>
          <div className="invoice-feed-table-wrap credit-notes-table">
            <table className="invoice-feed-table" data-testid="credit-notes-table">
              <thead>
                <tr>
                  <th scope="col">Number</th>
                  <th scope="col">Type</th>
                  <th scope="col">Date</th>
                  <th scope="col">Customer</th>
                  <th scope="col">Invoice</th>
                  <th scope="col" style={{ textAlign: 'right' }}>Amount</th>
                  <th scope="col">Status</th>
                </tr>
              </thead>
              <tbody>
                {notes.map((note) => (
                  <tr
                    key={note.id}
                    id={`credit-note-${note.id}`}
                    className={deepLinkClass(highlightId === note.id, note.status === 'cancelled' ? 'is-cancelled' : '')}
                  >
                    <td style={{ whiteSpace: 'nowrap' }}>
                      <button type="button" className="link-button" onClick={() => onView(note)}>
                        {note.credit_note_number}
                      </button>
                    </td>
                    <td>{voucher(note)} · {typeLabels[note.credit_note_type]}</td>
                    <td style={{ whiteSpace: 'nowrap' }}>{formatDate(note.credit_note_date ?? note.created_at)}</td>
                    <td>{customerName(note)}</td>
                    <td>{creditNoteInvoiceLabels(note.invoice_ids, invoices)}</td>
                    <td style={{ textAlign: 'right' }}>{formatCurrency(note.total_amount, currencyCode)}</td>
                    <td><StatusChip status={note.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="stack credit-notes-cards" style={{ gap: '12px' }}>
            {notes.map((note) => (
              <div
                key={note.id}
                id={`credit-note-${note.id}-card`}
                className={deepLinkClass(highlightId === note.id, 'panel')}
                style={{ padding: '16px' }}
              >
                <div className="panel__header">
                  <div>
                    <p className="eyebrow">{voucher(note)} · {typeLabels[note.credit_note_type]}</p>
                    <h3 className="nav-panel__title" style={{ fontSize: '1rem' }}>{note.credit_note_number}</h3>
                  </div>
                  <StatusChip status={note.status} />
                </div>
                <p className="muted-text" style={{ margin: '0 0 10px' }}>
                  {customerName(note)} • {formatDate(note.credit_note_date ?? note.created_at)} • Invoice {creditNoteInvoiceLabels(note.invoice_ids, invoices)}
                </p>
                {note.direction === 'inward' && note.supplier_credit_note_number ? (
                  // The number the user reconciles against GSTR-2B, so it
                  // belongs on the card rather than one click away.
                  <p className="muted-text" style={{ margin: '0 0 10px' }}>
                    Supplier CN {note.supplier_credit_note_number}
                    {note.supplier_credit_note_date ? ` dated ${formatDate(note.supplier_credit_note_date)}` : ''}
                  </p>
                ) : null}
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', flexWrap: 'wrap', alignItems: 'center' }}>
                  <strong>{formatCurrency(note.total_amount, currencyCode)}</strong>
                  <button type="button" className="button button--secondary" onClick={() => onView(note)}>
                    <FileText size={16} aria-hidden="true" />
                    View
                  </button>
                </div>
              </div>
            ))}
          </div>
        </>
      ) : null}

      <Pagination
        page={page}
        totalPages={totalPages}
        total={total}
        pageSize={pageSize}
        onPageChange={onPageChange}
        itemLabel="credit notes"
      />
    </>
  );
}
