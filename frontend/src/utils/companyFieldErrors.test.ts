import { describe, expect, it } from 'vitest';
import { companyIdentityErrors, firstIdentityErrorField } from './companyFieldErrors';

describe('companyIdentityErrors', () => {
  it('keeps the GSTIN, PAN and TAN messages and drops the rest', () => {
    const errors = companyIdentityErrors([
      { field: 'tan', message: 'TAN must look like ABCD12345E.' },
      { field: 'name', message: 'Name is required.' },
      { field: 'pan', message: 'PAN must look like ABCDE1234F.' },
      { field: 'tan', message: 'second TAN message' },
    ]);
    expect(errors).toEqual({ tan: 'TAN must look like ABCD12345E.', pan: 'PAN must look like ABCDE1234F.' });
  });

  it('focuses the first field in form order', () => {
    expect(firstIdentityErrorField({ tan: 'x', pan: 'y' })).toBe('pan');
    expect(firstIdentityErrorField({ tan: 'x' })).toBe('tan');
    expect(firstIdentityErrorField({})).toBeNull();
  });
});
