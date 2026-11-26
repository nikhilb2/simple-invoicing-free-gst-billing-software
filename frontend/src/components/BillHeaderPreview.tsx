/** One-row sketch of the top of a bill, shown under the business name on first setup. */
export default function BillHeaderPreview({ name }: { name: string }) {
  const trimmed = name.trim();
  return (
    <div className="bill-header-preview" aria-hidden="true">
      <span className={trimmed ? 'bill-header-preview__name' : 'bill-header-preview__name bill-header-preview__name--empty'}>
        {trimmed || 'Your business name'}
      </span>
      <span className="field-hint bill-header-preview__meta">
        TAX INVOICE<span className="bill-header-preview__number"> · Bill 1</span>
      </span>
    </div>
  );
}
