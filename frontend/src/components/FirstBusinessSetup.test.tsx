import { renderToString } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import FirstBusinessSetup, { SETUP_GSTIN_HINT, SETUP_NAME_HINT } from './FirstBusinessSetup';

const noop = () => undefined;

function render(over: Partial<Parameters<typeof FirstBusinessSetup>[0]> = {}) {
  return renderToString(
    <FirstBusinessSetup
      name="Ravi Kumar"
      onNameChange={noop}
      gst=""
      onGstChange={noop}
      gstOpen={false}
      onOpenGst={noop}
      busy={false}
      onSubmit={noop}
      {...over}
    />,
  );
}

/** Asserts each piece appears, in this order. */
function expectInOrder(html: string, pieces: string[]) {
  let from = 0;
  for (const piece of pieces) {
    const at = html.indexOf(piece, from);
    expect(at, `"${piece}" after position ${from}`).toBeGreaterThanOrEqual(0);
    from = at + piece.length;
  }
}

describe('FirstBusinessSetup (the first-run screen)', () => {
  it('says what it is in one line', () => {
    const html = render();
    expectInOrder(html, ['Getting started', 'Add your business', 'One detail and you can make your first bill.']);
  });

  it('has only the name, the bill header strip, its hint, the GSTIN link and Start billing, in that order', () => {
    const html = render();
    expectInOrder(html, [
      '>Business name</label>',
      'id="company-name"',
      'class="bill-header-preview"',
      'Ravi Kumar</span>',
      'TAX INVOICE',
      ' · Bill 1</span>',
      SETUP_NAME_HINT,
      'class="link-button link-button--tap company-setup__gst-link"',
      'Have a GSTIN? Add it',
      'class="button button--primary company-setup__submit"',
      'Start billing',
    ]);
    expect(html).toContain('placeholder="e.g. Sharma General Store"');
  });

  it('leaves out everything the old screen asked or said', () => {
    const html = render();
    for (const gone of [
      'Fields marked',
      'required-mark',
      '*</span>',
      'Your business<',
      'Company setup',
      'Address',
      'bank and cash accounts',
      'form-save-bar',
      'Create business and continue',
      'This goes on top of your bills',
      'id="company-gst"',
    ]) {
      expect(html, gone).not.toContain(gone);
    }
  });

  it('opens the GSTIN field in place of the link', () => {
    const html = render({ gstOpen: true, gst: '27ABCDE1234F1Z0' });
    expect(html).not.toContain('Have a GSTIN? Add it');
    expectInOrder(html, ['GSTIN (optional)</label>', 'id="company-gst"', SETUP_GSTIN_HINT, 'Start billing']);
    expect(html).toContain('value="27ABCDE1234F1Z0"');
  });

  it('shows a GSTIN format error under the GSTIN field', () => {
    const html = render({ gstOpen: true, gst: '27ABC', gstError: 'Enter all 15 characters of the GSTIN.' });
    expectInOrder(html, ['id="company-gst"', SETUP_GSTIN_HINT, 'id="company-gst-error"', 'Enter all 15 characters']);
    expect(html).toMatch(/id="company-gst"[^>]*aria-invalid="true"/);
  });

  it('puts the empty-name error in the hint’s slot, under the field, and marks the field invalid', () => {
    const html = render({ name: '', nameError: 'Enter your business name.' });
    expectInOrder(html, [
      'id="company-name"',
      'Your business name',
      '<div class="company-setup__hint-slot"><p class="field-error" id="company-name-error" role="alert">Enter your business name.</p></div>',
      'Have a GSTIN? Add it',
      'Start billing',
    ]);
    expect(html).not.toContain(SETUP_NAME_HINT);
    expect(html).toMatch(/id="company-name"[^>]*aria-invalid="true"/);
    expect(html).toMatch(/id="company-name"[^>]*aria-describedby="company-name-error"/);
  });

  it('looks busy, not dead, while starting, and nothing can be changed', () => {
    const html = render({ busy: true });
    expect(html).toContain('Starting…');
    expect(html).not.toContain('Starting...');
    expect(html).not.toContain('Start billing');
    expect(html).toMatch(/<button type="submit" class="button button--primary company-setup__submit is-busy" disabled="" aria-busy="true"/);
    expect(html).toMatch(/id="company-name"[^>]*readonly=""/i);
    // The GSTIN link cannot open the field mid-save.
    expect(html).toMatch(/company-setup__gst-link" disabled=""/);
    const open = render({ busy: true, gstOpen: true });
    expect(open).toMatch(/id="company-gst"[^>]*readonly=""/i);
  });

  it('says a failed save under the button and keeps the typed name', () => {
    const html = render({ saveError: 'Couldn’t save. Check your internet and try again.' });
    expectInOrder(html, ['value="Ravi Kumar"', 'Start billing', 'id="company-setup-save-error"', 'Couldn’t save. Check your internet and try again.']);
    expect(html).toMatch(/company-setup__submit"[^>]*aria-describedby="company-setup-save-error"/);
  });

  it('shows the hero while the profile loads, with no form yet', () => {
    const html = render({ loading: true });
    expect(html).toContain('Add your business');
    expect(html).toContain('Loading company profile...');
    expect(html).not.toContain('<form');
  });
});
