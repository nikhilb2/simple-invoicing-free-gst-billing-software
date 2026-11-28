import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import ComposerTotals, { type ComposerTotalsProps } from './ComposerTotals';
import { billDiscountHint, copiedDocumentNote, oldDocumentNote, signedCurrency } from '../composerTotalsText';

const noop = () => {};
const discount = (over: Partial<ComposerTotalsProps['discount']> = {}): ComposerTotalsProps['discount'] => ({
  open: true, type: 'net', value: '50', amount: 50, invalid: false, validity: '',
  onOpen: noop, onTypeChange: noop, onValueChange: noop, ...over,
});

function render(over: Partial<ComposerTotalsProps> = {}) {
  return renderToStaticMarkup(
    <ComposerTotals
      mode="before_tax"
      currencyCode="INR"
      subtotal={300}
      discount={discount()}
      taxableAmount={250}
      gstRows={[{ label: 'CGST', amount: 22.5 }, { label: 'SGST', amount: 22.5 }]}
      total={295}
      hint={billDiscountHint([18])}
      {...over}
    />,
  );
}

/** The row labels in page order. */
const labels = (html: string) => [...html.matchAll(/<div class="composer-totals__row[^"]*"><(?:span|label)[^>]*>([^<]+)</g)].map((m) => m[1]);

describe('ComposerTotals (issue 1154)', () => {
  it('flat ₹50 before GST: Subtotal, Discount, Taxable value, CGST, SGST, Total, then the hint', () => {
    const html = render();
    expect(labels(html)).toEqual(['Subtotal', 'Discount', 'Taxable value', 'CGST', 'SGST', 'Total']);
    expect(html).toContain('−₹50.00');
    expect(html).toContain('₹295.00');
    expect(html).toContain('GST is charged on the amount after the discount.');
    expect(html).toContain('id="invoice-bill-discount"');
    expect(html).toContain('inputMode="decimal"');
    expect(html).toContain('class="line-item__discount-modes"');
  });

  it('names a % discount and shows the round off', () => {
    const html = render({ discount: discount({ type: 'percentage', value: '10', amount: 30 }), roundOff: 0.4, total: 319 });
    expect(labels(html)).toEqual(['Subtotal', 'Discount (10%)', 'Taxable value', 'CGST', 'SGST', 'Round off', 'Total']);
    expect(html).toContain('−₹30.00');
    expect(html).toContain('₹0.40');
  });

  it('no discount: "+ Add discount", and no Subtotal or hint', () => {
    const html = render({ discount: discount({ open: false, value: '', amount: 0 }), taxableAmount: 300, total: 354, hint: null });
    expect(labels(html)).toEqual(['Discount', 'Taxable value', 'CGST', 'SGST', 'Total']);
    expect(html).toContain('+ Add discount');
    expect(html).not.toContain('field-hint');
  });

  it('an unusable value shows "—" and the message under the box', () => {
    const html = render({
      discount: discount({ value: '350', amount: 0, invalid: true, error: <small className="field-error field-error--block">Discount can&apos;t be more than the subtotal (₹300.00)</small> }),
      taxableAmount: 300, total: 354, hint: null,
    });
    expect(html).toContain('>—<');
    expect(html).toContain('Discount can&#x27;t be more than the subtotal (₹300.00)');
  });

  it('a document kept after GST shows its own order and the note', () => {
    const html = render({
      mode: 'after_tax', taxableAmount: 300, gstRows: [{ label: 'CGST', amount: 27 }, { label: 'SGST', amount: 27 }], total: 304, hint: null,
      note: { text: oldDocumentNote('invoice', false), action: { label: 'Take the discount before GST instead', onClick: noop } },
    });
    expect(labels(html)).toEqual(['Taxable value', 'CGST', 'SGST', 'Discount', 'Total']);
    expect(html).toContain('This invoice was saved with the discount taken after GST, so its totals stay as they were.');
    expect(html).toContain('Take the discount before GST instead');
    expect(html.indexOf('composer-totals__note')).toBeLessThan(html.indexOf('Taxable value'));
  });

  it('puts TCS after the GST and before the round off', () => {
    const html = render({ tcs: { label: 'TCS @ 1% (s.394(1))', amount: 2.95 }, roundOff: 0.05, total: 298 });
    expect(labels(html)).toEqual(['Subtotal', 'Discount', 'Taxable value', 'CGST', 'SGST', 'TCS @ 1% (s.394(1))', 'Round off', 'Total']);
  });
});

describe('the texts of the totals block', () => {
  it('words the hint for one rate and for several', () => {
    expect(billDiscountHint([18, 18])).toBe('GST is charged on the amount after the discount.');
    expect(billDiscountHint([5, 18])).toBe('GST is charged on the amount after the discount, shared across the items by their value.');
  });

  it('words the notes', () => {
    expect(oldDocumentNote('quotation', false)).toBe('This quotation was saved with the discount taken after GST, so its totals stay as they were.');
    expect(oldDocumentNote('invoice', true, { from: '₹304.00', to: '₹295.00' }))
      .toBe('The discount now comes off before GST. The total changes from ₹304.00 to ₹295.00 when you update.');
    expect(copiedDocumentNote('quotation', '₹304.00', '₹295.00'))
      .toBe('The quotation took the discount after GST (total ₹304.00). This invoice takes it before GST, so its total is ₹295.00.');
    expect(copiedDocumentNote('invoice', '₹304.00', '₹295.00'))
      .toBe('The invoice you copied took the discount after GST (total ₹304.00). This invoice takes it before GST, so its total is ₹295.00.');
  });

  it('signs amounts with a real minus', () => {
    expect(signedCurrency(-0.34, 'INR')).toBe('−₹0.34');
    expect(signedCurrency(0.4, 'INR')).toBe('₹0.40');
    expect(signedCurrency(-0.001, 'INR')).toBe('₹0.00');
  });
});
