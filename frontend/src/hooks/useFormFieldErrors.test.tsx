import { describe, expect, it } from 'vitest';
import { renderToString } from 'react-dom/server';
import { FieldError, LineFieldErrors, fieldErrorMessage } from './useFormFieldErrors';

describe('FieldError', () => {
  it('renders nothing for a field that passed', () => {
    expect(renderToString(<FieldError id="invoice-ledger" errors={{ 'invoice-date': 'Please fill out this field.' }} />)).toBe('');
  });

  it('renders the message under an id the field can point to', () => {
    const html = renderToString(<FieldError id="invoice-ledger" errors={{ 'invoice-ledger': 'Pick a ledger from the list.' }} />);
    expect(html).toContain('id="invoice-ledger-error"');
    expect(html).toContain('role="alert"');
    expect(html).toContain('Pick a ledger from the list.');
  });

  it('words a failed field in its own terms, and only while it has failed', () => {
    const html = renderToString(
      <FieldError id="invoice-price-1" errors={{ 'invoice-price-1': 'Value must be greater than or equal to 0.' }} text="Price can't be less than 0" className="line-item__error" />,
    );
    expect(html).toContain('Price can&#x27;t be less than 0');
    expect(html).toContain('class="field-error field-error--block line-item__error"');
    expect(renderToString(<FieldError id="invoice-price-1" errors={{}} text="Price can't be less than 0" />)).toBe('');
  });
});

const valid = { customError: false, valueMissing: false, rangeUnderflow: false, rangeOverflow: false, stepMismatch: false, badInput: false };

describe('fieldErrorMessage', () => {
  it('keeps a custom message, such as the comboboxes set', () => {
    expect(fieldErrorMessage({ ...valid, customError: true }, { validationMessage: 'Pick a product from the list.' }))
      .toBe('Pick a product from the list.');
  });

  it('shortens the browser wording for a narrow column', () => {
    expect(fieldErrorMessage({ ...valid, valueMissing: true }, { validationMessage: 'Please fill out this field.' })).toBe('Required');
    expect(fieldErrorMessage({ ...valid, rangeUnderflow: true }, { validationMessage: 'x', min: '1' })).toBe('Must be at least 1');
    expect(fieldErrorMessage({ ...valid, stepMismatch: true }, { validationMessage: 'x', step: '1' })).toBe('Use a whole number');
  });

  it('falls back to the browser message', () => {
    expect(fieldErrorMessage({ ...valid, stepMismatch: true }, { validationMessage: 'Enter a valid value.', step: '0.001' }))
      .toBe('Enter a valid value.');
  });
});

describe('LineFieldErrors', () => {
  const fields = [{ id: 'invoice-product-1', label: 'Product' }, { id: 'invoice-quantity-1', label: 'Qty' }];

  it('renders nothing when the line is fine', () => {
    expect(renderToString(<LineFieldErrors fields={fields} errors={{ 'invoice-ledger': 'Required' }} />)).toBe('');
  });

  it('names the field each message belongs to', () => {
    const html = renderToString(<LineFieldErrors fields={fields} errors={{ 'invoice-quantity-1': 'Required' }} />);
    expect(html).toContain('Qty: Required');
    expect(html).not.toContain('Product:');
  });
});
