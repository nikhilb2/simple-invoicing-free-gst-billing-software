import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import CreditNotesPage from './CreditNotesPage';
import CreditNotesList, { EMPTY_FILTERED, EMPTY_NO_NOTES } from './credit-notes/CreditNotesList';
import type { CreditNote } from '../types/api';

function renderPage(entry = '/credit-notes') {
  return renderToStaticMarkup(
    <MemoryRouter initialEntries={[entry]}>
      <CreditNotesPage />
    </MemoryRouter>,
  );
}

const note = (id: number, status: 'active' | 'cancelled' = 'active'): CreditNote => ({
  id,
  credit_note_number: `CN-${id}`,
  ledger_id: 1,
  financial_year_id: null,
  credit_note_type: 'return',
  direction: 'outward',
  supplier_credit_note_number: null,
  supplier_credit_note_date: null,
  credit_note_date: '2026-11-01',
  reason: null,
  status,
  taxable_amount: 100,
  cgst_amount: 9,
  sgst_amount: 9,
  igst_amount: 0,
  total_amount: 118,
  created_at: '2026-11-01T00:00:00Z',
  cancelled_at: null,
  invoice_ids: [5],
  items: [],
});

function renderList(props: Partial<Parameters<typeof CreditNotesList>[0]> = {}) {
  return renderToStaticMarkup(
    <CreditNotesList
      notes={[]}
      ledgers={[{ id: 1, name: 'Asha Stores' }]}
      invoices={[{ id: 5, invoice_number: 'INV-5' }]}
      currencyCode="INR"
      highlightId={null}
      loading={false}
      hasFilters={false}
      page={1}
      totalPages={1}
      total={0}
      pageSize={20}
      onPageChange={() => {}}
      onView={() => {}}
      onNew={() => {}}
      {...props}
    />,
  );
}

describe('CreditNotesPage', () => {
  it('has one h1, the Sales eyebrow and the New credit note button', () => {
    const html = renderPage();
    expect(html.match(/<h1/g)).toHaveLength(1);
    expect(html).toContain('>Credit / Debit Notes</h1>');
    expect(html).toContain('>Sales</p>');
    expect(html).toContain('New credit note');
    expect(html).toContain('Export CSV');
    expect(html).toContain('placeholder="Number or customer"');
    expect(html).toContain('More filters');
  });

  it('keeps the create form off the list page', () => {
    expect(renderPage()).not.toContain('credit-note-form-title');
  });

  it.each(['/credit-notes?invoice=5', '/credit-notes?ledger=3'])('opens the form for %s', (entry) => {
    const html = renderPage(entry);
    expect(html).toContain('credit-note-form-title');
    expect(html).toContain('modal-panel--credit-note-form');
  });
});

describe('CreditNotesList', () => {
  it('says there are no notes yet, with a primary button', () => {
    const html = renderList();
    expect(html).toContain(EMPTY_NO_NOTES);
    expect(html).toContain('button--primary');
  });

  it('says nothing matches when filters are set, without the button', () => {
    const html = renderList({ hasFilters: true });
    expect(html).toContain(EMPTY_FILTERED);
    expect(html).not.toContain('button--primary');
  });

  it('shows the loading message instead of the empty text', () => {
    const html = renderList({ loading: true });
    expect(html).toContain('Loading credit notes...');
    expect(html).not.toContain(EMPTY_NO_NOTES);
  });

  it('lists notes with status chips, one View button per card and the pager count', () => {
    const html = renderList({ notes: [note(1), note(2, 'cancelled')], total: 2 });
    for (const header of ['Number', 'Type', 'Date', 'Customer', 'Invoice', 'Amount', 'Status']) {
      expect(html).toContain(`>${header}</th>`);
    }
    expect(html).toContain('status-chip status-chip--success');
    expect(html).toContain('status-chip status-chip--cancelled');
    expect(html).not.toContain('style="background');
    expect(html).not.toContain('Cancel credit note');
    expect(html.match(/<\/svg>View<\/button>/g)).toHaveLength(2);
    expect(html).toMatch(/<strong>1–2<\/strong>\s*of 2 credit notes/);
  });

  it('flags the deep-linked note', () => {
    expect(renderList({ notes: [note(1)], total: 1, highlightId: 1 })).toContain('deep-link-target');
  });
});
