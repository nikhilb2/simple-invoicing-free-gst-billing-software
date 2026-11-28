import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, test } from 'vitest';
import GstRateSelect from './GstRateSelect';

const MESSAGE = 'Choose a GST rate. Pick 0% only if you charge no GST on this product.';

describe('GstRateSelect error (issue 1153)', () => {
  test('shows the message above the grey hint, and marks the select invalid', () => {
    const html = renderToStaticMarkup(<GstRateSelect id="gst" value="" onChange={() => {}} error={MESSAGE} />);
    expect(html).toContain(`<p class="field-error field-error--block" id="gst-error" role="alert">${MESSAGE}</p>`);
    expect(html).toMatch(/<select[^>]*aria-invalid="true"/);
    expect(html).toMatch(/<select[^>]*aria-describedby="gst-note gst-error"/);
    expect(html.indexOf('id="gst-error"')).toBeLessThan(html.indexOf('id="gst-note"'));
  });

  test('without an error it renders as before', () => {
    const html = renderToStaticMarkup(<GstRateSelect id="gst" value="" onChange={() => {}} />);
    expect(html).not.toContain('field-error');
    expect(html).not.toContain('aria-invalid');
    expect(html).toMatch(/<select[^>]*aria-describedby="gst-note"/);
  });
});
