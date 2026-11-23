import type { PdfPaper } from '../types/api';

export const PAPER_LABELS: Record<PdfPaper, string> = {
  a4: 'A4',
  a5: 'A5',
  thermal80: 'Thermal 80mm',
  thermal58: 'Thermal 58mm',
};

export const REPORT_PAPERS: PdfPaper[] = ['a4', 'a5'];

/** The paper a picker starts on: the company default, but A4 for a report when that default is thermal. */
export const initialPaper = (def: PdfPaper | undefined, report = false): PdfPaper =>
  !def || (report && def.startsWith('thermal')) ? 'a4' : def;
