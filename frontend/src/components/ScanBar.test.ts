import { expect, test } from 'vitest';
import { pasteSerialsLabel } from './ScanBar';

test('paste button label uses the singular for one serial', () => {
  expect(pasteSerialsLabel(0)).toBe('Add serials');
  expect(pasteSerialsLabel(1)).toBe('Add 1 serial');
  expect(pasteSerialsLabel(2)).toBe('Add 2 serials');
});
