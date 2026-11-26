import { describe, expect, it } from 'vitest';
import {
  composerSubmitReason,
  discountProblem,
  fieldProblemMessage,
  inPageOrder,
  priceProblem,
  quantityProblem,
  type ComposerProblem,
} from './composerProblems';

describe('composerSubmitReason', () => {
  it('is empty when nothing stops the save', () => {
    expect(composerSubmitReason([])).toBe('');
  });

  it('states a single problem as a sentence', () => {
    expect(composerSubmitReason([{ kind: 'product', line: 2 }])).toBe('Pick a product for line 2.');
    expect(composerSubmitReason([{ kind: 'quantity-min', line: 1 }])).toBe('Enter a quantity of 1 or more for line 1.');
    expect(composerSubmitReason([{ kind: 'price-min', line: 1 }])).toBe("Price can't be less than 0 for line 1.");
    expect(composerSubmitReason([{ kind: 'customer' }])).toBe('Choose a customer.');
    expect(composerSubmitReason([{ kind: 'customer' }], 'supplier')).toBe('Choose a supplier.');
  });

  it('counts the rest when there are more', () => {
    expect(composerSubmitReason([{ kind: 'product', line: 2 }, { kind: 'quantity-min', line: 3 }]))
      .toBe('Pick a product for line 2, and 1 more to fix.');
    expect(composerSubmitReason([
      { kind: 'product', line: 2 },
      { kind: 'quantity-min', line: 3 },
      { kind: 'discount-max', line: 3 },
    ])).toBe('Pick a product for line 2, and 2 more to fix.');
  });

  it('leads with the first problem in page order, whatever order they come in', () => {
    const mixed: ComposerProblem[] = [
      { kind: 'serial', line: 1 },
      { kind: 'price-min', line: 2 },
      { kind: 'quantity-missing', line: 2 },
      { kind: 'product', line: 3 },
      { kind: 'customer' },
    ];
    expect(inPageOrder(mixed).map((problem) => problem.kind))
      .toEqual(['customer', 'serial', 'quantity-missing', 'price-min', 'product']);
    expect(composerSubmitReason(mixed)).toBe('Choose a customer, and 4 more to fix.');
    expect(composerSubmitReason(mixed.filter((problem) => problem.kind !== 'customer')))
      .toBe('Line 1 has no serial number yet. Add one to create the invoice, and 3 more to fix.');
    expect(composerSubmitReason(mixed.filter((problem) => problem.kind !== 'customer' && problem.kind !== 'serial')))
      .toBe('Enter a quantity for line 2, and 2 more to fix.');
  });

  it('keeps the wording of #1035 for serials, naming every line that needs them', () => {
    expect(composerSubmitReason([{ kind: 'serial', line: 1 }]))
      .toBe('Line 1 has no serial number yet. Add one to create the invoice.');
    expect(composerSubmitReason([{ kind: 'serial', line: 3 }, { kind: 'serial', line: 1 }]))
      .toBe('Lines 1 and 3 have no serial number yet. Add one to each to create the invoice.');
    expect(composerSubmitReason([{ kind: 'serial', line: 1 }, { kind: 'serial', line: 3 }, { kind: 'price-min', line: 2 }]))
      .toBe('Lines 1 and 3 have no serial number yet. Add one to each to create the invoice, and 1 more to fix.');
  });
});

describe('line field rules', () => {
  it('reads the quantity', () => {
    expect(quantityProblem('', false)).toBe('quantity-missing');
    expect(quantityProblem('0', false)).toBe('quantity-min');
    expect(quantityProblem('-2', false)).toBe('quantity-min');
    expect(quantityProblem('1.5', false)).toBe('quantity-whole');
    expect(quantityProblem('3', false)).toBeNull();
    expect(quantityProblem('0.5', true)).toBeNull();
    expect(quantityProblem('0', true)).toBe('quantity-positive');
  });

  it('reads the price, and a blank one only when the catalogue has no price', () => {
    expect(priceProblem('-5', 450)).toBe('price-min');
    expect(priceProblem('0', 0)).toBeNull();
    expect(priceProblem('', 450)).toBeNull();
    expect(priceProblem('', 0)).toBe('price-missing');
    expect(priceProblem('', null)).toBeNull();
  });

  it('reads the discount', () => {
    expect(discountProblem('', 'percentage')).toBeNull();
    expect(discountProblem('-1', 'net')).toBe('discount-min');
    expect(discountProblem('120', 'percentage')).toBe('discount-max');
    expect(discountProblem('120', 'net')).toBeNull();
  });

  it('words the message under each field', () => {
    expect(fieldProblemMessage('product')).toBe('Pick a product from the list');
    expect(fieldProblemMessage('quantity-missing')).toBe('Enter a quantity');
    expect(fieldProblemMessage('quantity-min')).toBe('Enter 1 or more');
    expect(fieldProblemMessage('quantity-whole')).toBe('Use a whole number');
    expect(fieldProblemMessage('price-min')).toBe("Price can't be less than 0");
    expect(fieldProblemMessage('discount-min')).toBe("Discount can't be below 0");
    expect(fieldProblemMessage('discount-max')).toBe("Discount can't be more than 100%");
    expect(fieldProblemMessage('price-check')).toBeNull();
  });
});
