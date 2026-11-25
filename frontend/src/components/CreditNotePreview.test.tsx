import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import type { PreviewAction } from './PreviewToolbar';
import CreditNotePreview from './CreditNotePreview';

// The menu is closed in static markup, so capture what the preview hands the toolbar.
let menu: PreviewAction[] = [];
vi.mock('./PreviewToolbar', () => ({
  default: (props: { menu?: PreviewAction[] }) => {
    menu = props.menu ?? [];
    return null;
  },
}));

function render(props: Partial<Parameters<typeof CreditNotePreview>[0]> = {}) {
  menu = [];
  renderToStaticMarkup(
    <QueryClientProvider client={new QueryClient()}>
      <CreditNotePreview creditNoteId={7} creditNoteNumber="CN-7" onClose={() => {}} {...props} />
    </QueryClientProvider>,
  );
  return menu.find((action) => /^Cancel/.test(action.label));
}

describe('CreditNotePreview cancel menu item', () => {
  it('is offered when the page passes onCancelNote, and runs it', () => {
    const onCancelNote = vi.fn();
    const item = render({ onCancelNote });
    expect(item?.label).toBe('Cancel credit note');
    expect(item?.disabled).toBe(false);
    item?.onClick();
    expect(onCancelNote).toHaveBeenCalledTimes(1);
  });

  it('is hidden when the note cannot be cancelled', () => {
    expect(render()).toBeUndefined();
  });

  it('is disabled and says so while cancelling', () => {
    const item = render({ onCancelNote: () => {}, cancelling: true });
    expect(item?.label).toBe('Cancelling...');
    expect(item?.disabled).toBe(true);
  });

  it('names a debit note as one', () => {
    expect(render({ onCancelNote: () => {}, documentLabel: 'Debit Note' })?.title).toBe('Cancel this debit note');
  });
});
