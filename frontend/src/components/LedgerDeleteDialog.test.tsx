import { describe, expect, it } from 'vitest';
import { renderToString } from 'react-dom/server';
import LedgerDeleteDialog from './LedgerDeleteDialog';
import type { LedgerDeletePreview } from '../types/api';

const preview: LedgerDeletePreview = {
  ledger_id: 7,
  ledger_name: 'Sharma Traders',
  has_entries: true,
  to_cancel: {
    sales_invoices: 6,
    purchase_invoices: 0,
    receipts: 3,
    payments: 0,
    opening_balance: false,
    credit_notes: 1,
    delivery_challans: 0,
    quotations: 2,
    share_links: 0,
  },
  has_invoices_from_earlier_months: true,
};

function render(overrides: Partial<Parameters<typeof LedgerDeleteDialog>[0]> = {}) {
  return renderToString(
    <LedgerDeleteDialog
      ledgerName="Sharma Traders"
      preview={preview}
      canDelete
      busy={false}
      error=""
      onConfirm={() => {}}
      onCancel={() => {}}
      {...overrides}
    />,
  );
}

function deleteButton(html: string): string {
  const match = html.match(/<button[^>]*type="submit"[^>]*>[^<]*<\/button>/);
  return match ? match[0] : '';
}

describe('LedgerDeleteDialog', () => {
  it('lists what the delete cancels and warns about filed returns', () => {
    const html = render();
    expect(html).toContain('Delete <!-- -->Sharma Traders<!-- -->?');
    expect(html).toContain('This cancels 6 invoices, 3 receipts, 1 credit note and 2 quotations for this party.');
    expect(html).toContain('Stock on these invoices goes back.');
    expect(html).toContain('Invoices from past months may already be in a GSTR-1 you filed.');
    expect(html).toContain('You can&#x27;t undo this.');
  });

  it('keeps the delete button off until the ledger name is typed', () => {
    const html = render();
    expect(html).toContain('Type <strong>Sharma Traders</strong> to confirm');
    expect(deleteButton(html)).toContain('Delete ledger and cancel entries');
    expect(deleteButton(html)).toContain('disabled=""');
  });

  it('leaves out the GSTR-1 warning when every invoice is from this month', () => {
    const html = render({ preview: { ...preview, has_invoices_from_earlier_months: false } });
    expect(html).not.toContain('GSTR-1');
  });

  it('shows why the delete was refused inside the dialog', () => {
    const html = render({ error: 'Purchase invoice PUR-4 cannot be cancelled: SN-1 is sold. Nothing was changed.' });
    expect(html).toContain('role="alert"');
    expect(html).toContain('Purchase invoice PUR-4 cannot be cancelled');
  });

  it('tells a manager only an admin can do it, with no delete button', () => {
    const html = render({ canDelete: false });
    expect(html).toContain('Only an admin can delete a ledger that has entries.');
    expect(html).not.toContain('ledger-delete-confirm');
    expect(deleteButton(html)).toBe('');
    expect(html).toContain('Keep ledger');
  });

  it('says it is working while the delete runs', () => {
    expect(deleteButton(render({ busy: true }))).toContain('Deleting...');
  });
});
