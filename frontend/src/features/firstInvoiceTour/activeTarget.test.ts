import { readFileSync } from 'node:fs';
import { renderToStaticMarkup } from 'react-dom/server';
import { createElement } from 'react';
import { describe, expect, test, vi } from 'vitest';
import { ACTIVE_ATTRIBUTE, createActiveMarker, isWithinBand, stillTyping, visibleBand } from './activeTarget';

// The card's module reaches the auth store, which reads localStorage when it loads.
vi.stubGlobal('localStorage', { getItem: () => null, setItem: () => {}, removeItem: () => {} });

const fakeElement = () => {
  const attributes = new Map<string, string>();
  return {
    attributes,
    setAttribute: (name: string, value: string) => void attributes.set(name, value),
    removeAttribute: (name: string) => void attributes.delete(name),
  };
};

describe('data-tour-active', () => {
  test('moves from one target to the next, and is removed on exit', () => {
    const first = fakeElement();
    const second = fakeElement();
    const marker = createActiveMarker();

    marker.mark(first);
    expect(first.attributes.has(ACTIVE_ATTRIBUTE)).toBe(true);

    marker.mark(second);
    expect(first.attributes.has(ACTIVE_ATTRIBUTE)).toBe(false);
    expect(second.attributes.has(ACTIVE_ATTRIBUTE)).toBe(true);

    marker.mark(null);
    expect(second.attributes.has(ACTIVE_ATTRIBUTE)).toBe(false);
  });

  test('marking the same element again changes nothing', () => {
    const only = fakeElement();
    const marker = createActiveMarker();
    marker.mark(only);
    marker.mark(only);
    expect(only.attributes.size).toBe(1);
  });
});

describe('walkthrough card buttons', () => {
  const css = readFileSync(new URL('../../styles.css', import.meta.url), 'utf8');

  test('Exit walkthrough, Back to the invoice and Finish use the 44px button class', async () => {
    const { CoachCard } = await import('../../components/FirstInvoiceTourCoach');
    const html = renderToStaticMarkup(
      createElement(CoachCard, { step: 1, title: 't', body: 'b', onExit: () => {}, onBackToInvoice: () => {}, onFinish: () => {} }),
    );
    expect(html.match(/tour-coach__button/g)).toHaveLength(3);
    expect(html).not.toContain('button--small');
    expect(css).toMatch(/\.tour-coach__button\s*\{[^}]*min-height:\s*44px/);
  });

  test('the highlight is the target\'s own 2px accent outline at 4px, replacing its focus ring', () => {
    expect(css).toMatch(/\[data-tour-active\]\[data-tour-active\]:focus-visible\s*\{[^}]*outline:\s*2px solid rgb\(var\(--rgb-accent\)\)[^}]*outline-offset:\s*4px/);
    expect(css).not.toContain('.tour-ring');
  });

  test('a card whose target sits in the fixed Create invoice bar goes to the top, also above the bar offset', async () => {
    const { CoachCard } = await import('../../components/FirstInvoiceTourCoach');
    const html = renderToStaticMarkup(createElement(CoachCard, { step: 4, title: 't', body: 'b', placeOnTop: true }));
    expect(html).toContain('tour-coach tour-coach--top');
    expect(css).toMatch(/:root:not\(:has\(\[aria-modal='true'\]\)\) \.tour-coach--top,\s*\.tour-coach--top\s*\{[^}]*top:\s*12px;[^}]*bottom:\s*auto/);
  });
});

describe('the visible band', () => {
  // 390x844 phone: header 0-52, card at the bottom from 660.
  const phone = { viewportTop: 0, viewportBottom: 844, headerBottom: 52, card: { top: 660, bottom: 832 } };

  test('runs from 8px under the header to 12px above the card', () => {
    expect(visibleBand(phone)).toEqual({ top: 60, bottom: 648 });
  });

  test('a target tucked under the sticky header is out of view (the #1119 case: -1 to 41)', () => {
    expect(isWithinBand({ top: -1, bottom: 41 }, visibleBand(phone))).toBe(false);
    expect(isWithinBand({ top: 52, bottom: 94 }, visibleBand(phone))).toBe(false);
  });

  test('a target wholly inside the band is in view, edges included', () => {
    expect(isWithinBand({ top: 200, bottom: 244 }, visibleBand(phone))).toBe(true);
    expect(isWithinBand({ top: 60, bottom: 648 }, visibleBand(phone))).toBe(true);
  });

  test('a target within 12px of the card, or under it, is out of view', () => {
    expect(isWithinBand({ top: 600, bottom: 650 }, visibleBand(phone))).toBe(false);
    expect(isWithinBand({ top: 700, bottom: 740 }, visibleBand(phone))).toBe(false);
  });

  test('inside a dialog no header is counted', () => {
    expect(visibleBand({ ...phone, headerBottom: null }).top).toBe(0);
  });

  test('a card at the top bounds the band from above, 12px under it', () => {
    const top = { ...phone, card: { top: 12, bottom: 180 } };
    expect(visibleBand(top)).toEqual({ top: 192, bottom: 844 });
  });

  test('the shorter visible viewport (phone keyboard) shrinks the band', () => {
    expect(visibleBand({ ...phone, viewportBottom: 400, card: null }).bottom).toBe(400);
  });
});

describe('moving on while a field still has focus', () => {
  test('a focused field with a value counts as filled in once typing paused for 600ms', () => {
    expect(stillTyping(true, 'Asha', 100)).toBe(true);
    expect(stillTyping(true, 'Asha', 599)).toBe(true);
    expect(stillTyping(true, 'Asha', 600)).toBe(false);
  });

  test('an empty or untouched focused field is never done', () => {
    expect(stillTyping(true, '  ', 5000)).toBe(true);
    expect(stillTyping(true, 'prefilled', null)).toBe(true);
  });

  test('a field that is not focused is not being typed in', () => {
    expect(stillTyping(false, 'Asha', 0)).toBe(false);
  });
});
