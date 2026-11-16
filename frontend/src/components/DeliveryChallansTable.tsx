import { Link } from 'react-router-dom';
import type { DeliveryChallan } from '../types/api';
import {
  CHALLAN_PURPOSE_LABELS,
  CHALLAN_STATUS_LABELS,
  allowedChallanActions,
  challanStatusBadgeClass,
  formatChallanAge,
} from '../utils/deliveryChallan';
import formatCurrency, { formatDate } from '../utils/formatting';

type DeliveryChallansTableProps = {
  challans: DeliveryChallan[];
  onOpen: (challan: DeliveryChallan) => void;
  onConvert: (challan: DeliveryChallan) => void;
};

export default function DeliveryChallansTable({ challans, onOpen, onConvert }: DeliveryChallansTableProps) {
  return (
    <div className="invoice-feed-table-wrap">
      <table className="invoice-feed-table delivery-challans-table" data-testid="delivery-challans-table">
        <thead>
          <tr>
            <th scope="col">Number</th>
            <th scope="col">Date</th>
            <th scope="col">Party</th>
            <th scope="col">Purpose</th>
            <th scope="col" style={{ textAlign: 'right' }}>Value</th>
            <th scope="col">Status</th>
            <th scope="col">Age</th>
            <th scope="col">Invoice</th>
            <th scope="col" aria-label="Actions" />
          </tr>
        </thead>
        <tbody>
          {challans.map((challan) => {
            const canConvert = allowedChallanActions(challan).includes('convert');
            return (
              <tr key={challan.id} data-testid={`challan-row-${challan.id}`}>
                <td style={{ whiteSpace: 'nowrap' }}>
                  <button type="button" className="link-button" onClick={() => onOpen(challan)}>
                    {challan.challan_number}
                  </button>
                </td>
                <td style={{ whiteSpace: 'nowrap' }}>{formatDate(challan.challan_date)}</td>
                <td className="delivery-challans-table__party">{challan.ledger_name || '—'}</td>
                <td className="delivery-challans-table__purpose">{challan.purpose_label || CHALLAN_PURPOSE_LABELS[challan.purpose]}</td>
                <td style={{ textAlign: 'right' }}>
                  {formatCurrency(challan.taxable_amount, challan.company_currency_code || 'INR')}
                </td>
                <td>
                  <span className={challanStatusBadgeClass(challan.status)}>
                    {CHALLAN_STATUS_LABELS[challan.status]}
                  </span>
                </td>
                <td style={{ whiteSpace: 'nowrap' }}>
                  {challan.status === 'open' && challan.age_days !== null ? formatChallanAge(challan.age_days) : '—'}
                </td>
                <td style={{ whiteSpace: 'nowrap' }}>
                  {challan.invoice_number ? (
                    <Link to={`/invoices-view?search=${encodeURIComponent(challan.invoice_number)}`}>
                      {challan.invoice_number}
                    </Link>
                  ) : '—'}
                </td>
                <td className="delivery-challans-table__actions">
                  {canConvert ? (
                    <button
                      type="button"
                      className="button button--ghost button--small"
                      aria-label="Convert to invoice"
                      title="Convert to invoice"
                      onClick={() => onConvert(challan)}
                    >
                      Convert
                    </button>
                  ) : null}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
