import { describe, expect, test } from 'vitest';
import {
  GST_SLABS,
  HSN_ERROR,
  countsStockByDefault,
  hsnProblem,
  isGstSlab,
  plainProductError,
  productFieldProblems,
  shownFieldErrors,
  startsWithNoStock,
} from './productFormRules';

describe('GST slabs', () => {
  test('offers the standard rates and recognises them however they are written', () => {
    expect(GST_SLABS).toEqual([0, 5, 12, 18, 28, 40]);
    expect(isGstSlab('18')).toBe(true);
    expect(isGstSlab('5.00')).toBe(true);
    expect(isGstSlab('0')).toBe(true);
  });

  test('treats an unusual rate, or no choice yet, as not a slab', () => {
    expect(isGstSlab('')).toBe(false);
    expect(isGstSlab('0.25')).toBe(false);
    expect(isGstSlab('3')).toBe(false);
  });
});

describe('HSN/SAC', () => {
  test('accepts blank and 4, 6 or 8 digits', () => {
    for (const code of ['', ' ', '6109', '610910', '61091000']) expect(hsnProblem(code)).toBe('');
  });

  test('says what is wrong in words, not a column name', () => {
    for (const code of ['610', '61091', 'abcd']) expect(hsnProblem(code)).toBe(HSN_ERROR);
    expect(HSN_ERROR).not.toMatch(/hsn sac:/i);
  });

  test('rewrites the server message that names the column, and leaves others alone', () => {
    expect(plainProductError('Hsn sac: HSN/SAC must be 4, 6 or 8 digits')).toBe(HSN_ERROR);
    expect(plainProductError('SKU already exists')).toBe('SKU already exists');
  });
});

describe('opening stock', () => {
  test('flags a tracked product that starts at zero, and only that', () => {
    expect(startsWithNoStock(true, 0)).toBe(true);
    expect(startsWithNoStock(true, 4)).toBe(false);
    expect(startsWithNoStock(false, 0)).toBe(false);
  });
});

describe('stock counting for a new product (issue 983)', () => {
  test('is off for a company with no products, or none that count stock', () => {
    expect(countsStockByDefault([])).toBe(false);
    expect(countsStockByDefault([{ maintain_inventory: false }, { maintain_inventory: false }])).toBe(false);
  });

  test('stays on once the company counts stock for any product', () => {
    expect(countsStockByDefault([{ maintain_inventory: false }, { maintain_inventory: true }])).toBe(true);
  });
});

describe('field messages when a save is tapped with fields missing (issue 1153)', () => {
  const GST = 'Choose a GST rate. Pick 0% only if you charge no GST on this product.';
  const base = { name: 'Demo Atta 5kg', price: '', gstRate: '', priceNoun: 'selling price' };

  test('with only a name, the price and the GST rate each get their own message', () => {
    expect(productFieldProblems(base)).toEqual({ price: 'Enter a selling price.', gst: GST });
  });

  test('names every empty field, in page order', () => {
    expect(Object.keys(productFieldProblems({ ...base, name: ' ' }))).toEqual(['name', 'price', 'gst']);
    expect(productFieldProblems({ ...base, name: ' ' }).name).toBe('Product name is required.');
  });

  test('uses the quick-add label word, and says when the price is below 0', () => {
    expect(productFieldProblems({ ...base, priceNoun: 'unit price' }).price).toBe('Enter a unit price.');
    expect(productFieldProblems({ ...base, price: '-1' }).price).toBe('Selling price cannot be negative.');
    expect(productFieldProblems({ ...base, price: 'abc' }).price).toBe('Enter a selling price.');
  });

  test('0% is a real choice, and 0 a real price', () => {
    expect(productFieldProblems({ ...base, price: '0', gstRate: '0' })).toEqual({});
  });

  test('asks for opening stock only where it is counted and unanswered', () => {
    const filled = { ...base, price: '10', gstRate: '5' };
    expect(productFieldProblems({ ...filled, stockMissing: true })).toEqual({
      stock: 'Enter how many you have now, or untick Maintain inventory.',
    });
    expect(productFieldProblems({ ...filled, stockMissing: false })).toEqual({});
  });

  test('a valid form has no messages', () => {
    expect(productFieldProblems({ ...base, price: '120', gstRate: '5' })).toEqual({});
  });

  test('a message clears when its field is fixed and the others stay', () => {
    const flagged = ['price', 'gst'] as const;
    const before = shownFieldErrors(flagged, productFieldProblems(base));
    expect(Object.keys(before)).toEqual(['price', 'gst']);
    const priceFixed = shownFieldErrors(flagged, productFieldProblems({ ...base, price: '120' }));
    expect(Object.keys(priceFixed)).toEqual(['gst']);
    const gstFixed = shownFieldErrors(flagged, productFieldProblems({ ...base, gstRate: '18' }));
    expect(Object.keys(gstFixed)).toEqual(['price']);
  });

  test('a field that was never refused shows nothing, even while empty', () => {
    expect(shownFieldErrors([], productFieldProblems(base))).toEqual({});
  });
});
