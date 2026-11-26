import { renderToString } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import { ComposerNextStepHint } from './ComposerNextStep';

vi.mock('../store/useAuthStore', () => ({ useAuthStore: () => null }));
vi.mock('../store/useFirstInvoiceTourStore', () => ({ useFirstInvoiceTourStore: () => undefined }));

describe('ComposerNextStepHint', () => {
  it('says what is next, then offers to show how', () => {
    const html = renderToString(<ComposerNextStepHint onShowMeHow={() => undefined} />);
    expect(html).toContain('<p class="field-hint composer-next-step__line">Next: pick your customer, add an item, then tap Create invoice.</p>');
    expect(html).toContain('<button type="button" class="link-button link-button--tap composer-next-step__action">Show me how</button>');
    expect(html.indexOf('Next: pick')).toBeLessThan(html.indexOf('Show me how'));
  });

  it('leaves out "Show me how" for someone who could not finish the walkthrough', () => {
    const html = renderToString(<ComposerNextStepHint />);
    expect(html).toContain('Next: pick your customer');
    expect(html).not.toContain('Show me how');
  });
});
