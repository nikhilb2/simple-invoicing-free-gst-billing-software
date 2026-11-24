import { useState } from 'react';
import type { FormEvent } from 'react';
import { useEscapeClose } from '../hooks/useEscapeClose';
import type { LedgerDeletePreview } from '../types/api';
import { FILED_GSTR1_WARNING, ledgerDeletionWarnings, ledgerNameConfirmed } from '../utils/ledgerDeletion';
import ModalCloseButton from './ModalCloseButton';

type LedgerDeleteDialogProps = {
  ledgerName: string;
  preview: LedgerDeletePreview;
  /** Only admins may delete a ledger that has entries (#1050). */
  canDelete: boolean;
  busy: boolean;
  /** Why the last delete failed, e.g. the invoice that refused to cancel. */
  error: string;
  onConfirm: () => void;
  onCancel: () => void;
};

const noop = () => {};

/**
 * The warning before deleting a ledger that has entries: it cancels them all. The
 * delete button stays off until the ledger's name is typed. A refusal is shown here,
 * not in a toast, so it stays next to the button it is about.
 */
export default function LedgerDeleteDialog({
  ledgerName,
  preview,
  canDelete,
  busy,
  error,
  onConfirm,
  onCancel,
}: LedgerDeleteDialogProps) {
  const [typedName, setTypedName] = useState('');
  useEscapeClose(busy ? noop : onCancel);

  const confirmed = ledgerNameConfirmed(typedName, ledgerName);
  const lines = ledgerDeletionWarnings(preview.to_cancel);

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (confirmed && canDelete && !busy) onConfirm();
  }

  return (
    <div
      className="modal-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="ledger-delete-title"
      aria-describedby="ledger-delete-effects"
      onClick={busy ? undefined : onCancel}
    >
      <form
        className="modal-panel modal-panel--ledger-delete"
        onClick={(e) => e.stopPropagation()}
        onSubmit={handleSubmit}
        noValidate
      >
        <div className="panel__header">
          <h2 id="ledger-delete-title" className="nav-panel__title">Delete {ledgerName}?</h2>
          <ModalCloseButton onClick={onCancel} label={`Close delete ledger ${ledgerName}`} disabled={busy} />
        </div>

        <ul id="ledger-delete-effects" className="ledger-delete__effects">
          {lines.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
        {preview.has_invoices_from_earlier_months ? <p className="field-warning">{FILED_GSTR1_WARNING}</p> : null}
        {canDelete ? (
          <div className="field">
            <label htmlFor="ledger-delete-confirm">
              Type <strong>{ledgerName}</strong> to confirm
            </label>
            <input
              id="ledger-delete-confirm"
              className="input ledger-delete__confirm-input"
              value={typedName}
              onChange={(e) => setTypedName(e.target.value)}
              autoComplete="off"
              autoCapitalize="off"
              autoCorrect="off"
              spellCheck={false}
              disabled={busy}
            />
          </div>
        ) : (
          <p className="field-warning">
            Only an admin can delete a ledger that has entries. Ask an admin of this company to do it.
          </p>
        )}

        {error ? (
          <p className="form-error" role="alert">
            {error}
          </p>
        ) : null}

        <div className="form-action-bar ledger-delete__actions">
          <button type="button" className="button button--ghost" onClick={onCancel} disabled={busy}>
            Keep ledger
          </button>
          {canDelete ? (
            <button
              type="submit"
              className={`button button--danger${busy ? ' is-busy' : ''}`}
              disabled={!confirmed || busy}
            >
              {busy ? 'Deleting...' : 'Delete ledger and cancel entries'}
            </button>
          ) : null}
        </div>
      </form>
    </div>
  );
}
