import { readFileSync } from 'node:fs';
import { renderToStaticMarkup } from 'react-dom/server';
import { createElement } from 'react';
import { describe, expect, test, vi } from 'vitest';
import { ACTIVE_ATTRIBUTE, createActiveMarker } from './activeTarget';

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
