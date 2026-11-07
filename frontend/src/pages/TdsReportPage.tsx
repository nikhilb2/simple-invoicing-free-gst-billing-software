import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { getApiErrorMessage } from '../api/client';
import EmptyState from '../components/EmptyState';
import LoadingState from '../components/LoadingState';
import ScopeBar from '../components/ScopeBar';
import StatusToasts from '../components/StatusToasts';
import Tabs, { TabPanel } from '../components/Tabs';
import { downloadTdsCsv, fetchTdsReport, getBlobErrorMessage, setCertificateReceived } from '../features/tds/api';
import { certificateForm, currentTaxYear, quarterOptions, taxYearOptions } from '../features/tds/period';
import type { TdsKind, TdsReport, TdsTotal } from '../features/tds/types';
import formatCurrency, { formatDate, plural } from '../utils/formatting';

const TABS: { id: TdsKind; label: string }[] = [
  { id: 'receivable', label: 'TDS receivable' },
  { id: 'payable', label: 'TDS payable' },
];

const COPY: Record<TdsKind, string> = {
  receivable:
    'TDS your customers deducted from what they paid you. Match these rows against Form 26AS or AIS to claim the credit.',
  payable:
    'TDS you deducted from your suppliers. This is the input for Form 140 (Form 26Q for periods up to 31 March 2026).',
};

function TotalsTable({ title, firstColumn, totals }: { title: string; firstColumn: string; totals: TdsTotal[] }) {
  return (
    <section className="panel stack">
      <div className="panel__header">
        <div>
          <p className="eyebrow">Totals</p>
          <h2 className="nav-panel__title">{title}</h2>
        </div>
      </div>
      <div className="table-wrap">
        <table className="invoice-feed-table">
          <caption className="sr-only">{title}</caption>
          <thead>
            <tr>
              <th scope="col">{firstColumn}</th>
              <th scope="col">PAN</th>
              <th scope="col" className="text-right">Rows</th>
              <th scope="col" className="text-right">Taxable amount</th>
              <th scope="col" className="text-right">TDS</th>
            </tr>
          </thead>
          <tbody>
            {totals.map((t) => (
              <tr key={t.key}>
                <td>{t.label}</td>
                <td className="text-xs" style={{ fontFamily: 'monospace' }}>{t.pan || '-'}</td>
                <td className="text-right">{t.count}</td>
                <td className="text-right">{formatCurrency(t.base_amount)}</td>
                <td className="text-right">{formatCurrency(t.tds_amount)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export default function TdsReportPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const kind: TdsKind = searchParams.get('tab') === 'payable' ? 'payable' : 'receivable';

  const years = useMemo(() => taxYearOptions(), []);
  const [taxYear, setTaxYear] = useState(() => currentTaxYear());
  const [quarter, setQuarter] = useState<number | null>(null);
  const [report, setReport] = useState<TdsReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        setLoading(true);
        setError('');
        const data = await fetchTdsReport(kind, { taxYear, quarter });
        if (!cancelled) setReport(data);
      } catch (err) {
        if (cancelled) return;
        setReport(null);
        setError(getApiErrorMessage(err, 'Unable to load TDS report'));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [kind, taxYear, quarter]);

  function selectTab(id: TdsKind) {
    setSearchParams(id === 'receivable' ? {} : { tab: id }, { replace: true });
  }

  async function handleExport() {
    try {
      setDownloading(true);
      setError('');
      await downloadTdsCsv(kind, { taxYear, quarter });
    } catch (err) {
      setError(await getBlobErrorMessage(err, 'Unable to download TDS CSV'));
    } finally {
      setDownloading(false);
    }
  }

  async function toggleCertificate(allocationId: number, value: boolean) {
    const patch = (received: boolean) =>
      setReport((current) =>
        current
          ? {
              ...current,
              rows: current.rows.map((r) =>
                r.allocation_id === allocationId ? { ...r, certificate_received: received } : r,
              ),
            }
          : current,
      );
    patch(value);
    try {
      await setCertificateReceived(allocationId, value);
    } catch (err) {
      patch(!value);
      setError(getApiErrorMessage(err, 'Unable to update the certificate tick'));
    }
  }

  const rows = report?.rows ?? [];
  const receivable = kind === 'receivable';

  return (
    <div className="page-grid">
      <section className="page-hero">
        <div>
          <p className="eyebrow">Tax reports</p>
          <h1 className="page-title">TDS</h1>
          <p className="section-copy">{COPY[kind]}</p>
        </div>
        <div className="page-hero__aside">
          <div className="status-chip">{plural(rows.length, 'row')}</div>
        </div>
      </section>

      <StatusToasts
        error={error}
        success={success}
        onClearError={() => setError('')}
        onClearSuccess={() => setSuccess('')}
      />

      <Tabs tabs={TABS} value={kind} onChange={selectTab} label="TDS report" />

      <ScopeBar
        actions={(
          <button
            type="button"
            className="button button--secondary button--small"
            onClick={() => { void handleExport(); }}
            disabled={downloading}
          >
            {downloading ? 'Downloading…' : 'Export CSV'}
          </button>
        )}
      >
        <div className="field">
          <label htmlFor="tds-tax-year">Tax year</label>
          <select
            id="tds-tax-year"
            className="select"
            value={taxYear}
            onChange={(e) => setTaxYear(Number(e.target.value))}
          >
            {years.map((y) => (
              <option key={y.value} value={y.value}>{y.label}</option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="tds-quarter">Quarter</label>
          <select
            id="tds-quarter"
            className="select"
            value={quarter ?? ''}
            onChange={(e) => setQuarter(e.target.value === '' ? null : Number(e.target.value))}
          >
            {quarterOptions().map((q) => (
              <option key={q.label} value={q.value ?? ''}>{q.label}</option>
            ))}
          </select>
        </div>
      </ScopeBar>

      <TabPanel id={kind}>
        {loading ? <LoadingState message="Loading TDS report..." /> : null}
        {!loading && report && rows.length === 0 ? (
          <EmptyState message="No TDS recorded for this tax year and quarter." />
        ) : null}

        {!loading && report && rows.length > 0 ? (
          <div className="stack">
            <section className="panel stack">
              <div className="panel__header">
                <div>
                  <p className="eyebrow">{report.tax_year_label}</p>
                  <h2 className="nav-panel__title">
                    {receivable ? 'TDS deducted by customers' : 'TDS deducted from suppliers'}
                  </h2>
                </div>
                <div className="status-chip">
                  Total TDS {formatCurrency(report.total_tds)} on {formatCurrency(report.total_base)}
                </div>
              </div>
              <div className="table-wrap">
                <table className="invoice-feed-table">
                  <caption className="sr-only">TDS {kind} rows</caption>
                  <thead>
                    <tr>
                      <th scope="col">Party</th>
                      <th scope="col">PAN</th>
                      <th scope="col">{receivable ? 'Invoice' : 'Bill'}</th>
                      <th scope="col">{receivable ? 'Receipt' : 'Payment'}</th>
                      <th scope="col">Section</th>
                      <th scope="col" className="text-right">Rate</th>
                      <th scope="col" className="text-right">Taxable amount</th>
                      <th scope="col" className="text-right">TDS</th>
                      {receivable ? <th scope="col">Certificate</th> : null}
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => {
                      const form = certificateForm(r.deduction_date);
                      const number = receivable
                        ? r.invoice_number
                        : (r.supplier_invoice_number || r.invoice_number);
                      return (
                        <tr key={r.allocation_id}>
                          <td>{r.party_name}</td>
                          <td className="text-xs" style={{ fontFamily: 'monospace' }}>{r.party_pan || '-'}</td>
                          <td>
                            <strong className="text-xs">{number || '-'}</strong>
                            <div className="text-xs">{formatDate(r.invoice_date)}</div>
                          </td>
                          <td>
                            <strong className="text-xs">{r.payment_number || '-'}</strong>
                            <div className="text-xs">{formatDate(r.payment_date)}</div>
                          </td>
                          <td className="text-xs">{r.section_ref || '-'}</td>
                          <td className="text-right">{r.rate === null ? '-' : `${r.rate}%`}</td>
                          <td className="text-right">{formatCurrency(r.taxable_amount)}</td>
                          <td className="text-right">{formatCurrency(r.tds_amount)}</td>
                          {receivable ? (
                            <td>
                              <label className="text-xs">
                                <input
                                  type="checkbox"
                                  checked={r.certificate_received}
                                  onChange={(e) => { void toggleCertificate(r.allocation_id, e.target.checked); }}
                                  aria-label={`${form} received for ${r.party_name}, ${number || 'invoice'}`}
                                />{' '}
                                {form}
                              </label>
                            </td>
                          ) : null}
                        </tr>
                      );
                    })}
                  </tbody>
                  <tfoot>
                    <tr>
                      <th scope="row" colSpan={6}>Total</th>
                      <td className="text-right"><strong>{formatCurrency(report.total_base)}</strong></td>
                      <td className="text-right"><strong>{formatCurrency(report.total_tds)}</strong></td>
                      {receivable ? <td /> : null}
                    </tr>
                  </tfoot>
                </table>
              </div>
            </section>

            <TotalsTable title="Totals by section" firstColumn="Section" totals={report.totals_by_section} />
            <TotalsTable
              title={receivable ? 'Totals by customer' : 'Totals by supplier'}
              firstColumn={receivable ? 'Customer' : 'Supplier'}
              totals={report.totals_by_party}
            />
          </div>
        ) : null}
      </TabPanel>
    </div>
  );
}
