import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getApiErrorMessage, getBlobErrorMessage } from '../api/client';
import StatusToasts from '../components/StatusToasts';
import {
  downloadTcsReportCsv,
  fetchTcsReport,
  tcsReportQueryKey,
  type TcsReport,
} from '../api/tcsReports';
import formatCurrency from '../utils/formatting';

/* TCS is always rupees, whatever the display currency is. */
const CURRENCY = 'INR';
const QUARTERS = ['Q1 (Apr-Jun)', 'Q2 (Jul-Sep)', 'Q3 (Oct-Dec)', 'Q4 (Jan-Mar)'];

function money(value: string) {
  return formatCurrency(Number(value), CURRENCY);
}

export function taxYearLabel(year: number) {
  return `${year}-${String(year + 1).slice(2)}`;
}

function currentTaxYear(now = new Date()) {
  return now.getMonth() >= 3 ? now.getFullYear() : now.getFullYear() - 1;
}

export function returnNote(form: TcsReport['return_form']) {
  return form === 'Form 27EQ'
    ? 'These figures feed Form 27EQ (periods up to 31 March 2026).'
    : 'These figures feed Form 143 (Income-tax Rules 2026).';
}

export function TcsCollectedView({ report }: { report: TcsReport }) {
  return (
    <>
      <p className="section-copy" data-testid="tcs-return-note">{returnNote(report.return_form)}</p>
      <section className="content-grid content-grid--single">
        <article className="panel stack">
          <h2 className="nav-panel__title">Collections</h2>
          {report.rows.length === 0 ? (
            <div className="empty-state">No TCS was collected in this period.</div>
          ) : (
            <div className="table-wrap">
              <table className="invoice-feed-table">
                <caption className="sr-only">TCS collected</caption>
                <thead>
                  <tr>
                    <th scope="col">Document</th>
                    <th scope="col">Date</th>
                    <th scope="col">Buyer</th>
                    <th scope="col">PAN</th>
                    <th scope="col">Section</th>
                    <th scope="col" className="text-right">Base</th>
                    <th scope="col" className="text-right">Rate</th>
                    <th scope="col" className="text-right">TCS</th>
                  </tr>
                </thead>
                <tbody>
                  {report.rows.map((row) => (
                    <tr key={`${row.kind}-${row.id}-${row.section_ref ?? ''}-${row.tcs_amount}`} data-kind={row.kind}>
                      <td>
                        {row.document_number}
                        {row.kind === 'credit_note' ? (
                          <span className="status-chip" title={row.invoice_number ? `Against ${row.invoice_number}` : undefined}>
                            {' '}Credit note
                          </span>
                        ) : null}
                      </td>
                      <td>{row.date}</td>
                      <td>{row.buyer_name ?? ''}</td>
                      <td>{row.buyer_pan ?? 'No PAN'}</td>
                      <td>{row.section_ref ?? ''}</td>
                      <td className="text-right">{money(row.base_amount)}</td>
                      <td className="text-right">{Number(row.rate)}%</td>
                      <td className="text-right">{money(row.tcs_amount)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </article>
      </section>
      <section className="content-grid content-grid--single">
        <article className="panel stack">
          <h2 className="nav-panel__title">Totals by section</h2>
          <div className="table-wrap">
            <table className="invoice-feed-table" data-testid="tcs-totals">
              <thead>
                <tr>
                  <th scope="col">Section</th>
                  <th scope="col">Nature</th>
                  <th scope="col" className="text-right">Documents</th>
                  <th scope="col" className="text-right">Base</th>
                  <th scope="col" className="text-right">TCS</th>
                </tr>
              </thead>
              <tbody>
                {report.totals_by_section.map((total) => (
                  <tr key={`${total.section_ref}-${total.nature}`}>
                    <td>{total.section_ref ?? ''}</td>
                    <td>{total.nature ?? ''}</td>
                    <td className="text-right">{total.count}</td>
                    <td className="text-right">{money(total.base_amount)}</td>
                    <td className="text-right">{money(total.tcs_amount)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <th scope="row" colSpan={3}>Grand total (net of credit notes)</th>
                  <th className="text-right">{money(report.total_base)}</th>
                  <th className="text-right">{money(report.total_tcs)}</th>
                </tr>
              </tfoot>
            </table>
          </div>
        </article>
      </section>
    </>
  );
}

export default function TcsCollectedPage() {
  const thisYear = useMemo(() => currentTaxYear(), []);
  const [taxYear, setTaxYear] = useState(thisYear);
  const [quarter, setQuarter] = useState<number | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState('');
  const years = [thisYear, thisYear - 1, thisYear - 2, thisYear - 3];

  const query = useQuery({
    queryKey: tcsReportQueryKey(taxYear, quarter),
    queryFn: () => fetchTcsReport(taxYear, quarter),
    staleTime: 0,
  });
  const report = query.data;

  async function handleDownload() {
    try {
      setDownloading(true);
      setDownloadError('');
      await downloadTcsReportCsv(taxYear, quarter);
    } catch (err) {
      setDownloadError(await getBlobErrorMessage(err, 'Unable to download the TCS report'));
    } finally {
      setDownloading(false);
    }
  }

  return (
    <div className="page-grid">
      <section className="page-hero">
        <div>
          <p className="eyebrow">Tax reports</p>
          <h1 className="page-title">TCS collected</h1>
          <p className="section-copy">
            Tax collected at source on your sales invoices, net of credit notes, for your quarterly TCS return.
          </p>
        </div>
        <button
          type="button"
          className="button button--secondary button--small"
          onClick={() => { void handleDownload(); }}
          disabled={downloading || !report}
        >
          {downloading ? 'Downloading…' : 'Export CSV'}
        </button>
      </section>

      <StatusToasts
        error={downloadError}
        success=""
        onClearError={() => setDownloadError('')}
        onClearSuccess={() => {}}
      />

      <section className="panel">
        <div className="field">
          <label htmlFor="tcs-tax-year">Tax year</label>
          <select
            id="tcs-tax-year"
            className="input"
            value={taxYear}
            onChange={(e) => setTaxYear(Number(e.target.value))}
          >
            {years.map((year) => <option key={year} value={year}>{taxYearLabel(year)}</option>)}
          </select>
        </div>
        <div className="field">
          <label htmlFor="tcs-quarter">Quarter</label>
          <select
            id="tcs-quarter"
            className="input"
            value={quarter ?? ''}
            onChange={(e) => setQuarter(e.target.value === '' ? null : Number(e.target.value))}
          >
            <option value="">All quarters</option>
            {QUARTERS.map((label, index) => <option key={label} value={index + 1}>{label}</option>)}
          </select>
        </div>
      </section>

      {query.isError ? (
        <div className="empty-state" role="alert">
          {getApiErrorMessage(query.error, 'Unable to load the TCS report')}
        </div>
      ) : null}
      {query.isPending ? <div className="empty-state">Loading report…</div> : null}
      {report ? <TcsCollectedView report={report} /> : null}
    </div>
  );
}
