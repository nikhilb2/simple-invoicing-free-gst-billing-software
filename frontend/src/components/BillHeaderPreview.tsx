/** The bill title and number shown after the name, as on the first bill they will make. */
export const BILL_HEADER_META = 'TAX INVOICE · Bill 1';

/**
 * One-row sketch of the top of a bill, shown under the business name on first
 * setup (#1097). The meta sits right after the name, not at the far edge; a long
 * name ends in "…" and the meta never shrinks.
 */
export default function BillHeaderPreview({ name }: { name: string }) {
  const trimmed = name.trim();
  return (
    <div className="bill-header-preview" aria-hidden="true">
      <span className={trimmed ? 'bill-header-preview__name' : 'bill-header-preview__name bill-header-preview__name--empty'}>
        {trimmed || 'Your business name'}
      </span>
      <span className="field-hint bill-header-preview__meta">{BILL_HEADER_META}</span>
    </div>
  );
}
