import { describe, expect, it } from 'vitest';
import { keepInViewScroll } from './keepInView';

describe('keepInViewScroll', () => {
  it('does nothing when the button is already above the keyboard', () => {
    expect(keepInViewScroll({ targetBottom: 473, viewportBottom: 508, focusedTop: 219 })).toBe(0);
  });

  it('scrolls just enough to show the button with GSTIN open (390×844, 336px keyboard)', () => {
    // Measured on the branch: Start billing ends at 549.6 with GSTIN open.
    expect(keepInViewScroll({ targetBottom: 549.6, viewportBottom: 508, focusedTop: 400 })).toBeCloseTo(49.6);
  });

  it('never pushes the focused field above the top of the screen', () => {
    expect(keepInViewScroll({ targetBottom: 900, viewportBottom: 508, focusedTop: 100 })).toBe(92);
    expect(keepInViewScroll({ targetBottom: 900, viewportBottom: 508, focusedTop: 4 })).toBe(0);
  });
});
