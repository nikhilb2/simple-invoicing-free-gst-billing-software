import api from './client';

export type TcsReportForm = 'Form 27EQ' | 'Form 143';

/* The API sends money as decimal strings. */
export interface TcsReportRow {
  kind: 'invoice' | 'credit_note';
  id: number;
  document_number: string;
  date: string;
  invoice_number: string | null;
  buyer_name: string | null;
  buyer_pan: string | null;
  section_ref: string | null;
  nature: string | null;
  base_amount: string;
  rate: string;
  tcs_amount: string;
  /** "Declaration – not collected" (s.394(2), Form 27C) or "Not collected" on a sale with no TCS. */
  remark?: string | null;
}

export interface TcsSectionTotal {
  section_ref: string | null;
  nature: string | null;
  count: number;
  base_amount: string;
  tcs_amount: string;
  /** Sales under the section on which no TCS was collected; not in base_amount. */
  not_collected_base?: string;
}

export interface TcsReport {
  tax_year: number;
  quarter: number | null;
  from_date: string;
  to_date: string;
  return_form: TcsReportForm;
  rows: TcsReportRow[];
  totals_by_section: TcsSectionTotal[];
  total_base: string;
  total_tcs: string;
}

export const tcsReportQueryKey = (taxYear: number, quarter: number | null) =>
  ['reports', 'tcs-collected', taxYear, quarter] as const;

function params(taxYear: number, quarter: number | null) {
  return quarter === null ? { tax_year: taxYear } : { tax_year: taxYear, quarter };
}

export async function fetchTcsReport(taxYear: number, quarter: number | null): Promise<TcsReport> {
  const response = await api.get<TcsReport>('/reports/tcs-collected', { params: params(taxYear, quarter) });
  return response.data;
}

export async function downloadTcsReportCsv(taxYear: number, quarter: number | null): Promise<void> {
  const response = await api.get('/reports/tcs-collected/export-csv', {
    params: params(taxYear, quarter),
    responseType: 'blob',
  });
  const url = window.URL.createObjectURL(response.data as Blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `tcs_collected_${taxYear}-${String(taxYear + 1).slice(2)}${quarter ? `_Q${quarter}` : ''}.csv`;
  link.click();
  window.URL.revokeObjectURL(url);
}
