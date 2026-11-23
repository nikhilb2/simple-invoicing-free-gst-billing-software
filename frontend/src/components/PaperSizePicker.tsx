import type { PdfPaper } from '../types/api';
import { PAPER_LABELS, REPORT_PAPERS } from '../utils/paper';

type PaperSizePickerProps = {
  value: PdfPaper;
  onChange: (next: PdfPaper) => void;
  /** Reports only come in A4 and A5, so the thermal options are hidden. */
  reportOnly?: boolean;
  /** Sit in a page toolbar instead of a preview menu. */
  inline?: boolean;
};

/** Which paper the PDF is laid out for. Changing it refetches the preview. */
export default function PaperSizePicker({ value, onChange, reportOnly = false, inline = false }: PaperSizePickerProps) {
  const options = reportOnly ? REPORT_PAPERS : (Object.keys(PAPER_LABELS) as PdfPaper[]);
  return (
    <label className={inline ? 'paper-picker paper-picker--inline' : 'copies-stepper paper-picker'}>
      <span className="copies-stepper__label">Paper</span>
      <select
        className="paper-picker__select"
        value={value}
        onChange={(e) => onChange(e.target.value as PdfPaper)}
        aria-label="Paper size"
      >
        {options.map((paper) => (
          <option key={paper} value={paper}>{PAPER_LABELS[paper]}</option>
        ))}
      </select>
    </label>
  );
}
