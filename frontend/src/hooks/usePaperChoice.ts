import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { fetchCompanyProfile } from '../features/invoices/api';
import { initialPaper } from '../utils/paper';
import type { PdfPaper } from '../types/api';

/**
 * Returns `[shown, setPaper, requested]`. `shown` is for the picker: the user's pick, else the
 * company default (A4 for a report on thermal). `requested` is for requests: the user's pick
 * or undefined, so the backend applies the company default itself and the first fetch never
 * waits on the company query.
 */
export function usePaperChoice(report = false): [PdfPaper, (next: PdfPaper) => void, PdfPaper | undefined] {
  const { data } = useQuery({ queryKey: ['company', 'profile'], queryFn: fetchCompanyProfile, staleTime: 60_000 });
  const [picked, setPicked] = useState<PdfPaper | undefined>(undefined);
  return [picked ?? initialPaper(data?.default_pdf_paper, report), setPicked, picked];
}
