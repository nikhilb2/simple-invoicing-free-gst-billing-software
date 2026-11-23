import { useRef, useState } from 'react';
import api, { getApiErrorMessage } from '../../api/client';
import ModalCloseButton from '../../components/ModalCloseButton';
import { useEscapeClose } from '../../hooks/useEscapeClose';
import { plural } from '../../utils/formatting';

const endpoint = '/products/bulk-update';
const labels: Record<string, string> = {
  purchase_price: 'Purchase price (excl. GST)',
  price: 'Selling price (excl. GST)',
  hsn_sac: 'HSN/SAC',
  stock: 'Replacement stock',
};

type Preview = {
  token: string | null;
  errors: { row: number; message: string }[];
  changes: { id: number; name: string; fields: Record<string, { old: string | null; new: string }> }[];
};

export default function BulkUpdateModal({
  onClose,
  onSaved,
}: {
  onClose: () => void;
  onSaved: (count: number) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [confirmStock, setConfirmStock] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const pending = useRef(false);
  const hasStock = preview?.changes.some((change) => change.fields.stock);
  const close = () => { if (!pending.current) onClose(); };
  useEscapeClose(close);

  async function run(action: () => Promise<void>) {
    if (pending.current) return;
    pending.current = true;
    setBusy(true);
    setError('');
    try {
      await action();
    } catch (err) {
      setError(getApiErrorMessage(err, 'Bulk update could not be completed.'));
    } finally {
      pending.current = false;
      setBusy(false);
    }
  }

  async function download() {
    const { data } = await api.get<Blob>(endpoint + '/export', { responseType: 'blob' });
    const url = URL.createObjectURL(data);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'bulk-product-update.csv';
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  async function review() {
    if (!file) return;
    setPreview(null);
    setConfirmStock(false);
    const form = new FormData();
    form.append('file', file);
    const { data } = await api.post<Preview>(endpoint + '/preview', form);
    setPreview(data);
  }

  async function save() {
    if (!preview?.token || (hasStock && !confirmStock)) return;
    const { data } = await api.post<{ updated: number }>(endpoint + '/confirm', {
      token: preview.token,
      confirm_stock: confirmStock,
    });
    onSaved(data.updated);
  }

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true" aria-labelledby="bulk-update-title"
      onClick={(event) => { if (event.target === event.currentTarget) close(); }}>
      <div className="modal-panel">
        <div className="panel__header">
          <h2 id="bulk-update-title" className="nav-panel__title">Bulk update products</h2>
          <ModalCloseButton onClick={close} label="Close bulk product update" />
        </div>
        <div className="catalogue-import__body">
          <p className="field-hint">
            Edit the exported CSV and keep the product IDs. Blank cells leave values unchanged.
            Enter 0 to set a value to zero. Keep the HSN: prefix to preserve leading zeros.
          </p>
          <p className="field-hint">
            Set each price’s GST column to Inclusive or Exclusive. The preview shows the
            amount stored before GST. Current Stock is for reference. Use Replacement Stock
            only when you intend to set a new on-hand quantity.
          </p>
          <button type="button" className="button button--ghost" disabled={busy}
            onClick={() => void run(download)}>Download update CSV</button>
          <label htmlFor="bulk-update-csv">Updated CSV</label>
          <input id="bulk-update-csv" type="file" accept=".csv,text/csv" disabled={busy}
            onChange={(event) => {
              setFile(event.target.files?.[0] ?? null);
              setPreview(null);
              setConfirmStock(false);
              setError('');
            }} />
          <button type="button" className="button button--secondary" disabled={!file || busy}
            onClick={() => void run(review)}>Preview changes</button>
          {error && <p role="alert">{error}</p>}
          {preview && (
            <>
              {preview.errors.length > 0 && (
                <ul role="alert">
                  {preview.errors.map(({ row, message }) => <li key={row}>Row {row}. {message}</li>)}
                </ul>
              )}
              {preview.errors.length > 0 && preview.changes.length > 0 && (
                <p role="status">Fix the rows above in your CSV and preview again. Nothing can be saved until every row is valid.</p>
              )}
              {!preview.errors.length && !preview.changes.length && <p role="status">No changes found.</p>}
              {preview.changes.length > 0 && (
                <div style={{ overflowX: 'auto' }}>
                  <table className="table">
                    <caption>Proposed changes</caption>
                    <thead><tr><th>Product</th><th>Field</th><th>Old</th><th>New</th></tr></thead>
                    <tbody>
                      {preview.changes.flatMap((change) => Object.entries(change.fields).map(([field, values]) => (
                        <tr key={change.id + ':' + field}>
                          <td>{change.name} (#{change.id})</td>
                          <td>{labels[field]}</td>
                          <td>{values.old ?? '—'}</td>
                          <td>{values.new}</td>
                        </tr>
                      )))}
                    </tbody>
                  </table>
                </div>
              )}
              {preview.token && hasStock && (
                <label>
                  <input type="checkbox" checked={confirmStock} disabled={busy}
                    onChange={(event) => setConfirmStock(event.target.checked)} />
                  {' '}Confirm replacement of the stock quantities shown above
                </label>
              )}
              {preview.token && (
                <button type="button" className="button button--primary"
                  disabled={busy || (hasStock && !confirmStock)} onClick={() => void run(save)}>
                  Save {plural(preview.changes.length, 'product update')}
                </button>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
