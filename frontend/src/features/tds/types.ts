export type TdsKind = 'receivable' | 'payable';

export type TdsReportRow = {
  allocation_id: number;
  payment_id: number;
  payment_number: string | null;
  payment_date: string;
  invoice_id: number;
  invoice_number: string | null;
  supplier_invoice_number: string | null;
  invoice_date: string;
  deduction_date: string;
  quarter: number;
  ledger_id: number | null;
  party_name: string;
  party_pan: string | null;
  section_id: number | null;
  section_ref: string | null;
  rate: number | null;
  taxable_amount: number;
  base_amount: number | null;
  cash_amount: number;
  tds_amount: number;
  certificate_received: boolean;
};

export type TdsTotal = {
  key: string;
  label: string;
  pan: string | null;
  count: number;
  base_amount: number;
  tds_amount: number;
};

export type TdsReport = {
  kind: TdsKind;
  tax_year: number;
  tax_year_label: string;
  quarter: number | null;
  from_date: string;
  to_date: string;
  rows: TdsReportRow[];
  totals_by_section: TdsTotal[];
  totals_by_party: TdsTotal[];
  total_tds: number;
  total_base: number;
};

export type TdsReportParams = {
  taxYear: number;
  /** null means the whole tax year. */
  quarter: number | null;
};

export type TdsCertificateResult = {
  allocation_id: number;
  certificate_received: boolean;
};
