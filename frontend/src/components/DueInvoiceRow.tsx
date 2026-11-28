import { Link } from 'react-router-dom';
import type { Invoice } from '../types/api';
import formatCurrency from '../utils/formatting';
import { buildWhatsAppUrl, toWhatsAppNumber } from '../utils/phone';
import { buildWhatsAppReminderMessage } from '../utils/whatsappReminder';
import { dueBadgeLabel, formatInvoiceDateLabel, isOverdueInvoice } from '../utils/invoiceDueDate.ts';
import { canRecordPayment } from '../utils/invoicePayment';
import OverdueBadge from './OverdueBadge';

interface DueInvoiceRowProps {
  invoice: Invoice;
  currencyCode: string;
  onPreview: (invoiceId: number) => void;
  onRecordPayment: (invoice: Invoice) => void;
}

/**
 * One bill on the Dues page. It leads with the customer and the amount still
 * due (outstanding_amount), not the bill total, and gives one obvious next
 * step: a labelled "Remind on WhatsApp" button. Without a saved phone number
 * the button still works (wa.me asks which contact) and the row says why.
 */
export default function DueInvoiceRow({ invoice, currencyCode, onPreview, onRecordPayment }: DueInvoiceRowProps) {
  const currency = invoice.company_currency_code || currencyCode;
  const number = invoice.invoice_number || `#${invoice.id}`;
  const customer = invoice.ledger_name || 'Unknown ledger';
  const overdue = isOverdueInvoice(invoice);
  const whatsappUrl = buildWhatsAppUrl(
    toWhatsAppNumber(invoice.ledger_phone),
    buildWhatsAppReminderMessage({
      customerName: invoice.ledger_name,
      invoiceNumber: number,
      outstandingAmount: invoice.outstanding_amount,
      currencyCode: currency,
      dueDate: invoice.due_date,
      overdue,
    }),
  );
  const hasPhone = Boolean(toWhatsAppNumber(invoice.ledger_phone));
  const received = Number(invoice.paid_amount ?? 0);
  const customerPath = invoice.ledger_id ? `/ledgers/${invoice.ledger_id}` : null;

  return (
    <div className="invoice-row invoice-row--dues">
      <div className="invoice-row__meta">
        {customerPath ? (
          <Link className="invoice-row__ledger-name invoice-row__customer" to={customerPath}>{customer}</Link>
        ) : (
          <strong className="invoice-row__ledger-name invoice-row__customer">{customer}</strong>
        )}
        <span className="table-subtext">
          {number}
          {' · due '}
          {formatInvoiceDateLabel(invoice.due_date)}
          {' '}
          {overdue ? <OverdueBadge invoice={invoice} /> : <span className="table-subtext">{dueBadgeLabel(invoice.due_in_days)}</span>}
        </span>
        <span className="invoice-row__price">{formatCurrency(invoice.outstanding_amount, currency)} due</span>
        <span className="table-subtext">
          Bill {formatCurrency(invoice.total_amount, currency)}
          {received >= 0.005 ? <>{' · '}{formatCurrency(received, currency)} received</> : null}
        </span>
        {(invoice.tds_amount ?? 0) > 0 ? (
          <span className="table-subtext">
            {invoice.voucher_type === 'purchase' ? 'Paid to supplier' : 'Received'}{' '}
            {formatCurrency(invoice.paid_amount, currency)}
            {' · '}
            {invoice.voucher_type === 'purchase' ? 'TDS deducted' : 'TDS deducted by customer'}{' '}
            {formatCurrency(invoice.tds_amount ?? 0, currency)}
          </span>
        ) : null}
        {(invoice.ledger_payable_amount ?? 0) > 0 ? (
          <span className="table-subtext">
            You also owe this party {formatCurrency(invoice.ledger_payable_amount ?? 0, currencyCode)} (net{' '}
            {formatCurrency(Math.abs(invoice.ledger_net_receivable ?? 0), currencyCode)}{' '}
            {(invoice.ledger_net_receivable ?? 0) > 0 ? 'receivable' : 'payable'})
          </span>
        ) : null}
      </div>
      <div className="invoice-row__actions">
        <a
          className="button button--primary button--small invoice-row__remind"
          href={whatsappUrl}
          target="_blank"
          rel="noopener noreferrer"
          aria-label={`WhatsApp reminder to ${invoice.ledger_name || 'customer'}`}
        >
          Remind on WhatsApp
        </a>
        {!hasPhone ? (
          <div className="invoice-row__no-phone">
            <small className="field-hint">No phone number saved. WhatsApp will ask you to choose the contact.</small>
            {customerPath ? (
              <Link className="link-button link-button--tap" to={customerPath}>Add phone number</Link>
            ) : null}
          </div>
        ) : null}
        <div className="invoice-row__action-pair">
          {canRecordPayment(invoice) ? (
            <button
              type="button"
              className="button button--secondary button--small"
              onClick={() => onRecordPayment(invoice)}
              aria-label={`Payment received for invoice ${number}`}
            >
              Payment received
            </button>
          ) : null}
          <button
            type="button"
            className="button button--ghost button--small"
            onClick={() => onPreview(invoice.id)}
          >
            View bill
          </button>
        </div>
      </div>
    </div>
  );
}
