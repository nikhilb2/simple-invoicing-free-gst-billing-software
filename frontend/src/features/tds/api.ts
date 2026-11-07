import api, { getBlobErrorMessage } from '../../api/client';
import type {
  TdsCertificateResult,
  TdsKind,
  TdsReport,
  TdsReportParams,
} from './types';

function toQuery({ taxYear, quarter }: TdsReportParams) {
  return { tax_year: taxYear, quarter: quarter ?? undefined };
}

export async function fetchTdsReport(kind: TdsKind, params: TdsReportParams): Promise<TdsReport> {
  const response = await api.get<TdsReport>(`/tds/${kind}`, { params: toQuery(params) });
  return response.data;
}

/** Downloads the report CSV through the authenticated client. */
export async function downloadTdsCsv(kind: TdsKind, params: TdsReportParams): Promise<void> {
  const fallback = `tds_${kind}_${params.taxYear}-${String((params.taxYear + 1) % 100).padStart(2, '0')}${
    params.quarter ? `_q${params.quarter}` : ''
  }.csv`;
  const response = await api.get(`/tds/${kind}/csv`, {
    params: toQuery(params),
    responseType: 'blob',
  });
  const disposition = String(response.headers?.['content-disposition'] ?? '');
  const filename = /filename="?([^";]+)"?/i.exec(disposition)?.[1] ?? fallback;
  const url = window.URL.createObjectURL(response.data as Blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  window.URL.revokeObjectURL(url);
}

export async function setCertificateReceived(
  allocationId: number,
  certificateReceived: boolean,
): Promise<TdsCertificateResult> {
  const response = await api.patch<TdsCertificateResult>(`/tds/allocations/${allocationId}`, {
    certificate_received: certificateReceived,
  });
  return response.data;
}

export { getBlobErrorMessage };
