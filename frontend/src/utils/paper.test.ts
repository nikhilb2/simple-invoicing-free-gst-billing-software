import { describe, expect, it } from 'vitest';
import { initialPaper } from './paper';

describe('initialPaper', () => {
  it('uses the company default for a transaction', () => {
    expect(initialPaper('thermal80')).toBe('thermal80');
    expect(initialPaper('a5', true)).toBe('a5');
  });

  it('falls back to A4 for a report on thermal, or with no default', () => {
    expect(initialPaper('thermal58', true)).toBe('a4');
    expect(initialPaper(undefined)).toBe('a4');
  });
});
