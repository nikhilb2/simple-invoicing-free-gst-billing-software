import { useFY } from '../context/FYContext';
import { fyDateWarning } from '../utils/fyDateWarning';

/** Yellow hint under a document date field. `outcome` finishes "The … will still be ...". */
export default function FYDateWarning({ date, outcome }: { date: string | undefined; outcome: string }) {
  const { fyList, activeFY } = useFY();
  const text = fyDateWarning(
    date ?? '',
    fyList,
    activeFY,
    (label) => `⚠️ This date is outside the active financial year (${label}). ${outcome}`,
  );
  return text === null ? null : <p className="field-warning">{text}</p>;
}
