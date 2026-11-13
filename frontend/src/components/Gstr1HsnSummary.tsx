import type { Gstr1HsnSummaryItem } from '../types/api';
import formatCurrency from '../utils/formatting';

export default function Gstr1HsnSummary({ rows, currency }: {
  rows: Gstr1HsnSummaryItem[];
  currency: string;
}) {
  return (
    <section className="content-grid content-grid--single">
      <article className="panel stack">
        <div className="panel__header">
          <h2 className="nav-panel__title">HSN/SAC summary</h2>
          <div className="status-chip">{rows.length} rows</div>
        </div>
        <div className="table-wrap" style={{ maxHeight: 420, overflow: 'auto' }}>
          <table className="invoice-feed-table">
            <caption className="sr-only">HSN/SAC-wise summary</caption>
            <thead>
              <tr>
                <th scope="col">Buyer type</th>
                <th scope="col">HSN/SAC</th>
                <th scope="col">Description</th>
                <th scope="col">UQC</th>
                <th scope="col" className="text-right">GST rate</th>
                <th scope="col" className="text-right">Qty</th>
                <th scope="col" className="text-right">Taxable Value</th>
                <th scope="col" className="text-right">CGST</th>
                <th scope="col" className="text-right">SGST</th>
                <th scope="col" className="text-right">IGST</th>
                <th scope="col" className="text-right">Total Tax</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((item) => (
                <tr key={`${item.category}:${item.hsn_code}:${item.uqc}:${item.gst_rate}`}>
                  <td>{item.category ?? 'All buyers'}</td>
                  <td className="text-xs" style={{ fontFamily: 'monospace' }}>{item.hsn_code}</td>
                  <td>{item.description}</td>
                  <td>{item.uqc}</td>
                  <td className="text-right">{item.gst_rate}%</td>
                  <td className="text-right">{item.quantity.toFixed(3)}</td>
                  <td className="text-right">{formatCurrency(item.taxable_value, currency)}</td>
                  <td className="text-right">{formatCurrency(item.cgst, currency)}</td>
                  <td className="text-right">{formatCurrency(item.sgst, currency)}</td>
                  <td className="text-right">{formatCurrency(item.igst, currency)}</td>
                  <td className="text-right">{formatCurrency(item.total_tax, currency)}</td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr><td colSpan={11} className="text-xs text-center muted-text">No HSN data</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </article>
    </section>
  );
}
