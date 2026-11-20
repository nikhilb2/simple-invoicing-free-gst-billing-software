import { describe, expect, it } from 'vitest';
import { pageAfterOutOfRange } from './pagination';

describe('pageAfterOutOfRange', () => {
  it('steps back to the last page when a delete empties the current one', () => {
    expect(pageAfterOutOfRange(2, 1)).toBe(1);
  });

  it('jumps to the last page when several pages disappeared', () => {
    expect(pageAfterOutOfRange(5, 3)).toBe(3);
  });

  it('leaves a page that still exists alone', () => {
    expect(pageAfterOutOfRange(2, 2)).toBeNull();
    expect(pageAfterOutOfRange(1, 1)).toBeNull();
  });

  it('leaves a truly empty list alone so its empty state shows', () => {
    expect(pageAfterOutOfRange(2, 0)).toBeNull();
    expect(pageAfterOutOfRange(1, 0)).toBeNull();
  });
});
