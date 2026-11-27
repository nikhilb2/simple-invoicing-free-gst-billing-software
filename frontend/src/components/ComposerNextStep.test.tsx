import { renderToString } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import { ComposerNextStepHint } from './ComposerNextStep';

vi.mock('../store/useAuthStore', () => ({ useAuthStore: () => null }));
vi.mock('../store/useFirstInvoiceTourStore', () => ({ useFirstInvoiceTourStore: () => undefined }));

describe('ComposerNextStepHint', () => {
  it('says what is next, then offers to show how', () => {
    const html = renderToString(<ComposerNextStepHint ledgerChosen={false} productChosen={false} onShowMeHow={() => undefined} />);
    expect(html).toContain('<p class="field-hint composer-next-step__line">Next: pick your customer or add a new one.</p>');
    expect(html).toContain('<button type="button" class="link-button link-button--tap composer-next-step__action">Show me how</button>');
    expect(html.indexOf('Next: pick')).toBeLessThan(html.indexOf('Show me how'));
  });

  it('picks the line from what the form holds', () => {
    expect(renderToString(<ComposerNextStepHint ledgerChosen productChosen={false} onShowMeHow={() => undefined} />)).toContain('Next: add the first item.</p>');
    expect(renderToString(<ComposerNextStepHint ledgerChosen productChosen onShowMeHow={() => undefined} />)).toContain(
      'Next: check the total, then tap Create invoice.</p>',
    );
  });

  it('leaves out "Show me how" for someone who could not finish the walkthrough', () => {
    const html = renderToString(<ComposerNextStepHint ledgerChosen={false} productChosen={false} />);
    expect(html).toContain('Next: pick your customer');
    expect(html).not.toContain('Show me how');
  });
});
