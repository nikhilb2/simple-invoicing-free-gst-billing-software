/** The bill title shown after the name, as on the first bill they will make. */
export const BILL_HEADER_TITLE = 'TAX INVOICE';
/** The bill number after the title; hidden on phones (under 420px) so the name has room. */
export const BILL_HEADER_NUMBER = ' · Bill 1';

/**
 * One-row sketch of the top of a bill, shown under the business name on first
 * setup (#1097). The meta sits right after the name, not at the far edge; a long
 * name ends in "…" and the meta never shrinks. Under 420px the meta reads only
 * "TAX INVOICE", so a normal shop name fits on a phone (Naina, #1114).
 */
export default function BillHeaderPreview({ name }: { name: string }) {
  const trimmed = name.trim();
  return (
    <div className="bill-header-preview" aria-hidden="true">
      <span className={trimmed ? 'bill-header-preview__name' : 'bill-header-preview__name bill-header-preview__name--empty'}>
        {trimmed || 'Your business name'}
      </span>
      <span className="field-hint bill-header-preview__meta">
        {BILL_HEADER_TITLE}
        <span className="bill-header-preview__number">{BILL_HEADER_NUMBER}</span>
      </span>
    </div>
  );
}
