import { describe, expect, it } from 'vitest';
import { lineNeedsSerials, unserialedProductIds } from './serialLines';

describe('unserialedProductIds', () => {
  it('lists the products whose lines were billed without serials', () => {
    expect(unserialedProductIds([
      { product_id: 1, serials_applied: false },
      { product_id: 2, serials_applied: true },
      { product_id: 3, serials_applied: null },
      { product_id: 4 },
    ])).toEqual([1]);
  });

  it('leaves out a product that also has a line that carried serials', () => {
    expect(unserialedProductIds([
      { product_id: 1, serials_applied: false },
      { product_id: 1, serials_applied: true },
    ])).toEqual([]);
  });

  it('lists a product once', () => {
    expect(unserialedProductIds([
      { product_id: 1, serials_applied: false },
      { product_id: 1, serials_applied: false },
    ])).toEqual([1]);
  });
});

describe('lineNeedsSerials', () => {
  const tracked = { track_serials: true };
  const sale = { isQuote: false };

  it('needs serials on a tracked product', () => {
    expect(lineNeedsSerials({ productId: '1' }, tracked, sale)).toBe(true);
    expect(lineNeedsSerials({ productId: '1' }, tracked, { ...sale, unserialed: [] })).toBe(true);
  });

  it('needs none for an untracked product, a missing product or a quote', () => {
    expect(lineNeedsSerials({ productId: '1' }, { track_serials: false }, sale)).toBe(false);
    expect(lineNeedsSerials({ productId: '1' }, undefined, sale)).toBe(false);
    expect(lineNeedsSerials({ productId: '1' }, tracked, { isQuote: true })).toBe(false);
  });

  it('needs none on a line the edited invoice billed untracked, even though tracking is on now', () => {
    expect(lineNeedsSerials({ productId: '1' }, tracked, { ...sale, unserialed: [1] })).toBe(false);
  });

  it('still needs serials for another product on the same edited invoice', () => {
    expect(lineNeedsSerials({ productId: '2' }, tracked, { ...sale, unserialed: [1] })).toBe(true);
  });
});
