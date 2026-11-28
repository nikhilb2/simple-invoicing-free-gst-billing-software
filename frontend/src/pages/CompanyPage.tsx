import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import axios from 'axios';
import api, { getApiErrorCode, getApiErrorDetails, getApiErrorMessage } from '../api/client';
import { createTerm, deleteTerm, removeLogo, updateTerm, uploadLogo } from '../api/company';
import CurrencyChangeDialog from '../components/CurrencyChangeDialog';
import GstinInput from '../components/GstinInput';
import StatusToasts from '../components/StatusToasts';
import { useAuthStore } from '../store/useAuthStore';
import { useFYStore } from '../store/useFYStore';
import { useFirstInvoiceTourStore } from '../store/useFirstInvoiceTourStore';
import { canStartTour, INVOICE_PATH } from '../features/firstInvoiceTour/tourSteps';
import { useFY } from '../context/FYContext';
import { PAPER_LABELS } from '../utils/paper';
import type { CompanyProfile, CompanyProfileUpdate, InvoiceSeries, InvoiceSeriesUpdate, CompanyTermOut, PdfPaper } from '../types/api';
import { clearSetupDraft, companyFormCurrency, isCompanyConfigured, isCompanyFormDirty, missingCompanyFields, pickSetupNamePrefill, readSetupDraft, writeSetupDraft, type MissingCompanyFields } from '../utils/companySetup';
import { createSubmitGuard, isConnectionOrServerError, SAVE_FAILED_MESSAGE } from '../utils/saveFeedback';
import ConfirmDialog from '../components/ConfirmDialog';
import { isCurrencyChange } from '../utils/currencyChange';
import { buildSeriesPreview, clampNextSequenceInput, gstr1SeriesFormatError, MAX_NEXT_SEQUENCE, parseNextSequenceInput } from '../utils/seriesPreview';
import { purchaseTdsSetting } from '../utils/tds';
import { companyIdentityErrors, firstIdentityErrorField, type CompanyIdentityErrors } from '../utils/companyFieldErrors';
import { GSTIN_LENGTH, gstinError, normalizeGstinInput } from '../utils/gstin';
import FirstBusinessSetup from '../components/FirstBusinessSetup';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const VOUCHER_LABELS: Record<string, string> = {
  sales: 'Sales',
  purchase: 'Purchase',
  payment: 'Payment',
  credit_note: 'Credit Note',
  // Our own number for a credit note a supplier sent us. Kept out of the
  // credit note series so GSTR-1 Table 13 declares an unbroken range.
  debit_note: 'Debit Note (purchase returns)',
  quotation: 'Quotation',
  proforma: 'Proforma Invoice',
  delivery_challan: 'Delivery Challan',
};

const MAX_LOGO_SIZE_BYTES = 100 * 1024; // 100 KB

// ---------------------------------------------------------------------------
// LogoUploadCard
// ---------------------------------------------------------------------------

function LogoUploadCard({
  logoUrl,
  onLogoChanged,
}: {
  logoUrl: string | null;
  onLogoChanged: () => void;
}) {
  const [uploading, setUploading] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [error, setError] = useState('');

  async function handleFileSelected(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;

    if (file.size > MAX_LOGO_SIZE_BYTES) {
      setError('File size must be under 512 KB.');
      return;
    }

    const allowedTypes = ['image/png', 'image/jpeg', 'image/jpg'];
    if (!allowedTypes.includes(file.type)) {
      setError('Only PNG, JPG, and JPEG formats are supported.');
      return;
    }

    setError('');
    setUploading(true);
    try {
      const base64 = await fileToBase64(file);
      const data = base64.split(',')[1]; // strip data URI prefix
      await uploadLogo({ data, mime_type: file.type });
      onLogoChanged();
    } catch (err) {
      setError(getApiErrorMessage(err, 'Failed to upload logo'));
    } finally {
      setUploading(false);
      e.target.value = '';
    }
  }

  async function handleRemove() {
    setRemoving(true);
    setError('');
    try {
      await removeLogo();
      onLogoChanged();
    } catch (err) {
      setError(getApiErrorMessage(err, 'Failed to remove logo'));
    } finally {
      setRemoving(false);
    }
  }

  return (
    <div className="panel">
      <div className="panel__header">
        <div>
          <p className="eyebrow">Branding</p>
          <h3 className="nav-panel__title">Company Logo</h3>
        </div>
      </div>
      <p style={{ fontSize: '0.875rem', opacity: 0.7, marginBottom: '12px' }}>
        Upload your company logo (PNG, JPG, JPEG, max 100 KB). It will appear on all generated PDFs.
      </p>

      {error && <p style={{ color: 'var(--color-danger)', fontSize: '0.875rem', marginBottom: '8px' }}>{error}</p>}

      <div style={{ display: 'flex', alignItems: 'center', gap: '16px', flexWrap: 'wrap' }}>
        {logoUrl ? (
          <div style={{ border: '1px solid var(--line-neutral)', borderRadius: '8px', padding: '8px', background: 'var(--logo-frame-bg)' }}>
            <img src={logoUrl} alt="Company logo" style={{ maxWidth: '180px', maxHeight: '80px', objectFit: 'contain' }} />
          </div>
        ) : (
          <div style={{ border: '2px dashed var(--line-neutral-strong)', borderRadius: '8px', padding: '24px 32px', textAlign: 'center', color: 'var(--text-placeholder)', fontSize: '0.875rem' }}>
            No logo uploaded
          </div>
        )}

        <label className="button button--secondary" style={{ cursor: 'pointer' }}>
          {uploading ? 'Uploading…' : 'Choose file'}
          <input
            type="file"
            accept="image/png,image/jpeg,image/jpg"
            style={{ display: 'none' }}
            onChange={handleFileSelected}
            disabled={uploading}
          />
        </label>

        {logoUrl && (
          <button className="button button--danger" disabled={removing} onClick={handleRemove}>
            {removing ? 'Removing…' : 'Remove logo'}
          </button>
        )}
      </div>
    </div>
  );
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = () => reject(new Error('Failed to read file'));
    reader.readAsDataURL(file);
  });
}

// ---------------------------------------------------------------------------
// AdditionalInfoSection
// ---------------------------------------------------------------------------

function AdditionalInfoSection({
  value,
  onSave,
  saving,
}: {
  value: string;
  onSave: (value: string) => Promise<void>;
  saving: boolean;
}) {
  const [draft, setDraft] = useState(value);
  const [localError, setLocalError] = useState('');
  const [localSuccess, setLocalSuccess] = useState('');

  useEffect(() => {
    setDraft(value);
  }, [value]);

  async function handleSave() {
    setLocalError('');
    setLocalSuccess('');
    try {
      await onSave(draft);
      setLocalSuccess('Additional info saved');
      setTimeout(() => setLocalSuccess(''), 2500);
    } catch (err) {
      setLocalError(getApiErrorMessage(err, 'Failed to save'));
    }
  }

  return (
    <div className="panel">
      <div className="panel__header">
        <div>
          <p className="eyebrow">Branding</p>
          <h3 className="nav-panel__title">Additional Company Information</h3>
        </div>
      </div>
      <p style={{ fontSize: '0.875rem', opacity: 0.7, marginBottom: '12px' }}>
        Text displayed below the logo on all generated PDFs. Use this for taglines, registration details, compliance statements, etc.
      </p>

      {localError && <p style={{ color: 'var(--color-danger)', fontSize: '0.875rem', marginBottom: '8px' }}>{localError}</p>}
      {localSuccess && <p style={{ color: 'var(--color-success)', fontSize: '0.875rem', marginBottom: '8px' }}>{localSuccess}</p>}

      <textarea
        className="textarea"
        aria-label="Additional company information"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        placeholder={`Example:
ABC Enterprises Pvt. Ltd.
Authorized Distributor of Industrial Products
GSTIN: 07ABCDE1234F1Z2
Customer Care: +91 XXXXX XXXXX`}
        rows={5}
        style={{ width: '100%', minHeight: '120px', resize: 'vertical' }}
      />

      <div className="button-row" style={{ marginTop: '12px' }}>
        <button className="button button--primary" disabled={saving} onClick={handleSave}>
          {saving ? 'Saving…' : 'Save'}
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// TermsAndConditionsCard
// ---------------------------------------------------------------------------

function TermsAndConditionsCard({ companyId }: { companyId: number }) {
  const [terms, setTerms] = useState<CompanyTermOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [newTermContent, setNewTermContent] = useState('');
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editContent, setEditContent] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  useEffect(() => {
    loadTerms();
  }, [companyId]);

  async function loadTerms() {
    setLoading(true);
    try {
      const res = await api.get<CompanyTermOut[]>('/company/terms');
      setTerms(res.data);
    } catch {
      // non-admin
    } finally {
      setLoading(false);
    }
  }

  async function handleAddTerm() {
    const content = newTermContent.trim();
    if (!content) return;
    setSaving(true);
    setError('');
    try {
      await createTerm({ content });
      setNewTermContent('');
      await loadTerms();
      setSuccess('Term added');
      setTimeout(() => setSuccess(''), 2500);
    } catch (err) {
      setError(getApiErrorMessage(err, 'Failed to add term'));
    } finally {
      setSaving(false);
    }
  }

  async function handleUpdateTerm(termId: number) {
    const content = editContent.trim();
    if (!content) return;
    setSaving(true);
    setError('');
    try {
      await updateTerm(termId, { content });
      setEditingId(null);
      setEditContent('');
      await loadTerms();
      setSuccess('Term updated');
      setTimeout(() => setSuccess(''), 2500);
    } catch (err) {
      setError(getApiErrorMessage(err, 'Failed to update term'));
    } finally {
      setSaving(false);
    }
  }

  async function handleDeleteTerm(termId: number) {
    if (!confirm('Delete this term?')) return;
    setSaving(true);
    setError('');
    try {
      const updatedList = await deleteTerm(termId);
      setTerms(updatedList);
      setSuccess('Term deleted');
      setTimeout(() => setSuccess(''), 2500);
    } catch (err) {
      setError(getApiErrorMessage(err, 'Failed to delete term'));
    } finally {
      setSaving(false);
    }
  }

  function startEdit(term: CompanyTermOut) {
    setEditingId(term.id);
    setEditContent(term.content);
  }

  function cancelEdit() {
    setEditingId(null);
    setEditContent('');
  }

  if (loading) return <div className="empty-state">Loading terms…</div>;

  return (
    <div className="panel">
      <div className="panel__header">
        <div>
          <p className="eyebrow">Terms &amp; Conditions</p>
          <h3 className="nav-panel__title">Invoice Terms</h3>
        </div>
      </div>
      <p style={{ fontSize: '0.875rem', opacity: 0.7, marginBottom: '12px' }}>
        Manage terms that will appear on Sales and Tax Invoices. Terms are automatically serial numbered and appear in order.
      </p>

      {error && <p style={{ color: 'var(--color-danger)', fontSize: '0.875rem', marginBottom: '8px' }}>{error}</p>}
      {success && <p style={{ color: 'var(--color-success)', fontSize: '0.875rem', marginBottom: '8px' }}>{success}</p>}

      {/* Add new term */}
      <div style={{ display: 'flex', gap: '8px', marginBottom: '16px' }}>
        <input
          className="input"
          aria-label="New invoice term"
          value={newTermContent}
          onChange={(e) => setNewTermContent(e.target.value)}
          placeholder="Add a new term..."
          style={{ flex: 1 }}
          onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); void handleAddTerm(); } }}
        />
        <button
          className="button button--primary"
          disabled={saving || !newTermContent.trim()}
          onClick={handleAddTerm}
        >
          Add
        </button>
      </div>

      {/* Existing terms list */}
      {terms.length === 0 ? (
        <p style={{ fontSize: '0.875rem', color: 'var(--text-placeholder)' }}>No terms added yet.</p>
      ) : (
        <div className="stack" style={{ gap: '8px' }}>
          {terms.map((term) => (
            <div key={term.id} style={{ border: '1px solid var(--line-neutral)', borderRadius: '6px', padding: '10px 12px' }}>
              {editingId === term.id ? (
                <div>
                  <textarea
                    className="textarea"
                    aria-label={`Edit term ${term.serial_number}`}
                    value={editContent}
                    onChange={(e) => setEditContent(e.target.value)}
                    rows={2}
                    style={{ width: '100%', marginBottom: '8px', resize: 'vertical' }}
                  />
                  <div style={{ display: 'flex', gap: '8px' }}>
                    <button className="button button--primary" style={{ padding: '4px 12px', fontSize: '0.85rem' }} disabled={saving} onClick={() => void handleUpdateTerm(term.id)}>
                      Save
                    </button>
                    <button className="button button--ghost" style={{ padding: '4px 12px', fontSize: '0.85rem' }} onClick={cancelEdit}>
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '8px' }}>
                  <div style={{ flex: 1 }}>
                    <span style={{ fontWeight: 600, fontSize: '0.875rem', marginRight: '8px' }}>{term.serial_number}.</span>
                    <span style={{ fontSize: '0.875rem' }}>{term.content}</span>
                  </div>
                  <div style={{ display: 'flex', gap: '6px', flexShrink: 0 }}>
                    <button className="button button--secondary" style={{ padding: '2px 10px', fontSize: '0.8rem' }} onClick={() => startEdit(term)}>
                      Edit
                    </button>
                    <button className="button button--danger" style={{ padding: '2px 10px', fontSize: '0.8rem' }} disabled={saving} onClick={() => void handleDeleteTerm(term.id)}>
                      Delete
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// InvoiceSeriesCard
// ---------------------------------------------------------------------------

type SeriesRowState = Required<InvoiceSeriesUpdate>;

function InvoiceSeriesCard({ sectionRef, savedGstin }: { sectionRef?: React.RefObject<HTMLElement>; savedGstin: string }) {
  const { activeFY, loading: fyLoading } = useFY();
  const [seriesList, setSeriesList] = useState<InvoiceSeries[]>([]);
  const [drafts, setDrafts] = useState<Record<number, SeriesRowState>>({});
  const [nextSequenceText, setNextSequenceText] = useState<Record<number, string>>({});
  const [saving, setSaving] = useState<Record<number, boolean>>({});
  const [rowError, setRowError] = useState<Record<number, string>>({});
  const [rowSuccess, setRowSuccess] = useState<Record<number, string>>({});
  const [loading, setLoading] = useState(true);
  const saveInFlightRef = useRef<Record<number, boolean>>({});

  useEffect(() => {
    if (fyLoading) return;

    let cancelled = false;
    setLoading(true);
    void (async () => {
      try {
        const params: Record<string, string | number> = {};
        if (activeFY) params.financial_year_id = activeFY.id;
        const res = await api.get<InvoiceSeries[]>('/invoice-series/', { params });
        if (cancelled) return;
        setSeriesList(res.data);
        const initial: Record<number, SeriesRowState> = {};
        const initialText: Record<number, string> = {};
        for (const s of res.data) {
          initialText[s.id] = String(s.next_sequence);
          initial[s.id] = {
            prefix: s.prefix,
            suffix: s.suffix,
            include_year: s.include_year,
            year_format: s.year_format,
            separator: s.separator,
            pad_digits: s.pad_digits,
            next_sequence: s.next_sequence,
          };
        }
        setDrafts(initial);
        setNextSequenceText(initialText);
      } catch {
        // non-admin users won't see this card
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [activeFY?.id, fyLoading]);

  function patchDraft(id: number, patch: Partial<SeriesRowState>) {
    setDrafts((prev) => ({ ...prev, [id]: { ...prev[id], ...patch } }));
  }

  function changeNextSequence(id: number, raw: string) {
    const bounded = clampNextSequenceInput(raw);
    setNextSequenceText((prev) => ({ ...prev, [id]: bounded }));
    const value = parseNextSequenceInput(bounded);
    if (value !== null) patchDraft(id, { next_sequence: value });
  }

  function nextSequenceTextOf(id: number): string {
    return nextSequenceText[id] ?? String(drafts[id]?.next_sequence ?? '');
  }

  async function saveSeries(s: InvoiceSeries) {
    const draft = drafts[s.id];
    if (!draft) return;
    if (saveInFlightRef.current[s.id]) return;
    saveInFlightRef.current[s.id] = true;
    setSaving((prev) => ({ ...prev, [s.id]: true }));
    setRowError((prev) => ({ ...prev, [s.id]: '' }));
    setRowSuccess((prev) => ({ ...prev, [s.id]: '' }));
    try {
      const res = await api.put<InvoiceSeries>(`/invoice-series/${s.id}`, draft);
      setSeriesList((prev) => prev.map((x) => (x.id === s.id ? res.data : x)));
      setNextSequenceText((prev) => ({ ...prev, [s.id]: String(res.data.next_sequence) }));
      setRowSuccess((prev) => ({ ...prev, [s.id]: 'Saved' }));
      setTimeout(() => setRowSuccess((prev) => ({ ...prev, [s.id]: '' })), 2500);
    } catch (err) {
      setRowError((prev) => ({ ...prev, [s.id]: getApiErrorMessage(err, 'Failed to save') }));
    } finally {
      saveInFlightRef.current[s.id] = false;
      setSaving((prev) => ({ ...prev, [s.id]: false }));
    }
  }

  if (loading) return <article className="panel stack"><div className="empty-state">Loading series…</div></article>;
  if (seriesList.length === 0) return null;

  return (
    <article className="panel stack" id="invoice-series-settings" ref={sectionRef} tabIndex={-1}>
      <div className="panel__header">
        <div>
          <p className="eyebrow">Numbering</p>
          <h2 className="nav-panel__title">
            Invoice series{activeFY ? ` — FY ${activeFY.label}` : ''}
          </h2>
        </div>
      </div>
      <p style={{ fontSize: '0.875rem', opacity: 0.7, marginBottom: '8px' }}>
        Configure the prefix, suffix, year, and sequence counter for each voucher type.
        Changes apply to the next invoice created — existing numbers are not affected.
      </p>

      <div className="stack" style={{ gap: '24px' }}>
        {seriesList.map((s) => {
          const draft = drafts[s.id];
          if (!draft) return null;
          const fyStartYear = activeFY?.start_date ? Number(activeFY.start_date.slice(0, 4)) : null;
          const preview = buildSeriesPreview(draft, draft.next_sequence, activeFY?.label, undefined, fyStartYear);
          const longest = buildSeriesPreview(draft, Math.max(draft.next_sequence, 9999), activeFY?.label, undefined, fyStartYear);
          const formatError = gstr1SeriesFormatError(draft, s, savedGstin, activeFY?.label, undefined, fyStartYear);
          const nextSequenceInvalid = parseNextSequenceInput(nextSequenceTextOf(s.id)) === null;
          return (
            <div key={s.id} className="panel" style={{ padding: '16px' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
                <strong style={{ textTransform: 'capitalize' }}>{VOUCHER_LABELS[s.voucher_type] ?? s.voucher_type}</strong>
              </div>

              <div className="field-grid">
                <div className="field">
                  <label htmlFor={`series-prefix-${s.id}`}>Prefix</label>
                  <input
                    id={`series-prefix-${s.id}`}
                    className="input"
                    value={draft.prefix}
                    onChange={(e) => patchDraft(s.id, { prefix: e.target.value.toUpperCase() })}
                    placeholder="INV"
                    style={{ textTransform: 'uppercase' }}
                  />
                </div>

                <div className="field">
                  <label htmlFor={`series-suffix-${s.id}`}>Suffix</label>
                  <input
                    id={`series-suffix-${s.id}`}
                    className="input"
                    value={draft.suffix}
                    onChange={(e) => patchDraft(s.id, { suffix: e.target.value.toUpperCase() })}
                    placeholder="/A"
                    style={{ textTransform: 'uppercase' }}
                  />
                </div>

                <div className="field">
                  <label htmlFor={`series-sep-${s.id}`}>Separator</label>
                  <input
                    id={`series-sep-${s.id}`}
                    className="input"
                    value={draft.separator}
                    maxLength={3}
                    onChange={(e) => patchDraft(s.id, { separator: e.target.value })}
                    placeholder="-"
                  />
                </div>

                <div className="field">
                  <label htmlFor={`series-pad-${s.id}`}>Pad digits</label>
                  <select
                    id={`series-pad-${s.id}`}
                    className="select"
                    value={draft.pad_digits}
                    onChange={(e) => patchDraft(s.id, { pad_digits: Number(e.target.value) as 2 | 3 | 4 })}
                  >
                    <option value={2}>2 (e.g. 01)</option>
                    <option value={3}>3 (e.g. 001)</option>
                    <option value={4}>4 (e.g. 0001)</option>
                  </select>
                </div>

                <div className="field">
                  <label htmlFor={`series-year-fmt-${s.id}`}>Year format</label>
                  <select
                    id={`series-year-fmt-${s.id}`}
                    className="select"
                    value={draft.year_format}
                    disabled={!draft.include_year}
                    onChange={(e) => patchDraft(s.id, { year_format: e.target.value as 'YYYY' | 'MM-YYYY' | 'FY' })}
                  >
                    <option value="YYYY">YYYY (e.g. 2026)</option>
                    <option value="MM-YYYY">MM-YYYY (e.g. 04-2026)</option>
                    <option value="FY">FY (e.g. 2025-26)</option>
                  </select>
                </div>

                <div className="field">
                  <label htmlFor={`series-next-seq-${s.id}`}>Next number</label>
                  <input
                    id={`series-next-seq-${s.id}`}
                    className="input"
                    type="number"
                    min={1}
                    max={MAX_NEXT_SEQUENCE}
                    step={1}
                    value={nextSequenceTextOf(s.id)}
                    onChange={(e) => changeNextSequence(s.id, e.target.value)}
                    onBlur={() => {
                      if (nextSequenceInvalid) {
                        setNextSequenceText((prev) => ({ ...prev, [s.id]: String(draft.next_sequence) }));
                      }
                    }}
                    aria-invalid={nextSequenceInvalid ? true : undefined}
                    aria-describedby={nextSequenceInvalid ? `series-next-seq-error-${s.id}` : undefined}
                  />
                  {nextSequenceInvalid && (
                    <p className="field-error" id={`series-next-seq-error-${s.id}`} role="alert">
                      Enter a number from 1 to 999,999,999.
                    </p>
                  )}
                </div>

                <div className="field" style={{ display: 'flex', alignItems: 'center', gap: '8px', paddingTop: '22px' }}>
                  <input
                    id={`series-include-year-${s.id}`}
                    type="checkbox"
                    checked={draft.include_year}
                    onChange={(e) => patchDraft(s.id, { include_year: e.target.checked })}
                  />
                  <label htmlFor={`series-include-year-${s.id}`} style={{ marginBottom: 0, cursor: 'pointer' }}>Include year</label>
                </div>
              </div>

              <div style={{ marginTop: '12px', display: 'flex', alignItems: 'center', gap: '16px', flexWrap: 'wrap' }}>
                <div style={{ fontSize: '0.875rem', opacity: 0.7 }}>
                  <div>Preview: <strong>{preview}</strong> ({preview.length}/16)</div>
                  <div>Longest number: <strong>{longest}</strong> ({longest.length}/16)</div>
                </div>
                <button
                  className="button button--primary"
                  style={{ marginTop: 0, padding: '6px 16px', fontSize: '0.875rem' }}
                  disabled={saving[s.id] || Boolean(formatError) || nextSequenceInvalid}
                  onClick={() => void saveSeries(s)}
                >
                  {saving[s.id] ? 'Saving…' : 'Save'}
                </button>
                {rowSuccess[s.id] && <span style={{ color: 'var(--color-success)', fontSize: '0.875rem' }}>{rowSuccess[s.id]}</span>}
                {rowError[s.id] && <span style={{ color: 'var(--color-danger)', fontSize: '0.875rem' }}>{rowError[s.id]}</span>}
              </div>
              {formatError && <p className="field-error" role="alert">{formatError}</p>}
              {s.gstr1_warning ? <p className="field-warning" role="alert">{s.gstr1_warning}</p> : null}
            </div>
          );
        })}
      </div>
    </article>
  );
}

// ---------------------------------------------------------------------------
// EWayBillSettingsCard
// ---------------------------------------------------------------------------

function EWayBillSettingsCard({
  form,
  onChange,
}: {
  form: CompanyProfileUpdate;
  onChange: (patch: Partial<CompanyProfileUpdate>) => void;
}) {
  return (
    <div className="panel">
      <div className="panel__header">
        <div>
          <p className="eyebrow">GST &amp; E-Way Bill</p>
          <h3 className="nav-panel__title">E-Way Bill Configuration</h3>
        </div>
      </div>
      <p style={{ fontSize: '0.875rem', opacity: 0.7, marginBottom: '12px' }}>
        Configure thresholds and visibility rules for the E-Way Bill feature. Thresholds serve as guidance only and do not block generation.
      </p>

      <div className="field-grid">
        <div className="field field--full">
          <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', fontWeight: 600 }}>
            <input
              type="checkbox"
              checked={form.eway_enabled}
              onChange={(e) => onChange({ eway_enabled: e.target.checked })}
            />
            Enable E-Way Bill Generation
          </label>
          <small className="field-hint" style={{ marginLeft: '24px' }}>
            When disabled, the Generate E-Way Bill button will be hidden across the app.
          </small>
        </div>

        <div className="field">
          <label htmlFor="eway-local-threshold">Local E-Way Threshold Amount</label>
          <input
            id="eway-local-threshold"
            className="input"
            type="number"
            min={0}
            step={1}
            value={form.eway_local_threshold}
            onChange={(e) => onChange({ eway_local_threshold: parseFloat(e.target.value) || 0 })}
            disabled={!form.eway_enabled}
          />
          <small className="field-hint">
            Applied when seller and buyer are in the same state. ₹50,000 is the central rule (Rule 138), but your state may
            notify a different limit for movement within it, so check and set yours here.
          </small>
        </div>

        <div className="field">
          <label htmlFor="eway-interstate-threshold">Interstate E-Way Threshold Amount</label>
          <input
            id="eway-interstate-threshold"
            className="input"
            type="number"
            min={0}
            step={1}
            value={form.eway_interstate_threshold}
            onChange={(e) => onChange({ eway_interstate_threshold: parseFloat(e.target.value) || 0 })}
            disabled={!form.eway_enabled}
          />
          <small className="field-hint">
            Applied when seller and buyer are in different states. Default: ₹50,000 (Rule 138).
          </small>
        </div>

        <div className="field field--full">
          <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', fontWeight: 600 }}>
            <input
              type="checkbox"
              checked={form.eway_always_show_button}
              onChange={(e) => onChange({ eway_always_show_button: e.target.checked })}
              disabled={!form.eway_enabled}
            />
            Always Show E-Way Button
          </label>
          <small className="field-hint" style={{ marginLeft: '24px' }}>
            When enabled, the Generate E-Way Bill button is always visible (with threshold warnings).
            When disabled, the button is hidden for invoices below the threshold.
          </small>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// CompanyPage
// ---------------------------------------------------------------------------

const CASH_BANK_PATH = '/cash-bank/accounts';

export default function CompanyPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [searchParams] = useSearchParams();
  const seriesSectionRef = useRef<HTMLElement>(null);
  const gstInputRef = useRef<HTMLInputElement>(null);
  const nameInputRef = useRef<HTMLInputElement>(null);
  const addressInputRef = useRef<HTMLTextAreaElement>(null);
  const [missingFields, setMissingFields] = useState<MissingCompanyFields>({});
  // What the server holds, to tell unsaved edits apart. Null until a profile loads.
  const [savedForm, setSavedForm] = useState<CompanyProfileUpdate | null>(null);
  // Where to go once the pending save succeeds ("Save and open").
  const pendingNavRef = useRef<string | null>(null);
  const [leaveTarget, setLeaveTarget] = useState<string | null>(null);
  const formRef = useRef<HTMLFormElement>(null);
  const panInputRef = useRef<HTMLInputElement>(null);
  const tanInputRef = useRef<HTMLInputElement>(null);
  const [form, setForm] = useState<CompanyProfileUpdate>({
    name: '',
    address: '',
    gst: '',
    pan: '',
    tan: '',
    enable_purchase_tds: false,
    phone_number: '',
    currency_code: 'INR',
    email: '',
    website: '',
    show_sku_on_pdf: false,
    default_pdf_paper: 'a4' as PdfPaper,
    eway_enabled: true,
    eway_local_threshold: 50000,
    eway_interstate_threshold: 50000,
    eway_always_show_button: true,
    show_pay_qr_on_invoice: false,
    show_upi_pay_button: false,
    enable_tcs: false,
  });
  const [companyId, setCompanyId] = useState<number>(0);
  const [savedGstin, setSavedGstin] = useState('');
  const [savedCurrency, setSavedCurrency] = useState('');
  // Set once we know the company has invoices and the user is changing currency;
  // the dialog waits for their answer before anything is saved.
  const [showCurrencyWarning, setShowCurrencyWarning] = useState(false);
  // True when the server says this user has no company at all (409
  // company_required), so saving has to create one rather than update one.
  const [noCompany, setNoCompany] = useState(false);
  const [logoUrl, setLogoUrl] = useState<string | null>(null);
  const [additionalInfo, setAdditionalInfo] = useState('');
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  // First setup: claimed before the first await, so a second tap can never send
  // a second POST, and left claimed on success until the composer has opened.
  const [setupGuard] = useState(createSubmitGuard);
  const [setupSaveError, setSetupSaveError] = useState('');
  const [gstOpen, setGstOpen] = useState(false);
  const nameEditedRef = useRef(false);
  const [additionalSaving, setAdditionalSaving] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [initialSetupRequired, setInitialSetupRequired] = useState<boolean | null>(null);
  // GSTIN / PAN / TAN messages from a failed save, shown under each input.
  const [identityErrors, setIdentityErrors] = useState<CompanyIdentityErrors>({});
  const [gstTouched, setGstTouched] = useState(false);
  const invalidGst = gstinError(form.gst);
  const gstError = identityErrors.gst ?? (gstTouched || form.gst.length >= GSTIN_LENGTH ? invalidGst : null);
  // No "Complete company setup" popup any more: it was one more click between a
  // new user and the form, and read as homework. The short form says it instead.
  const setupRequiredByRoute = searchParams.get('setup') === 'required';
  // The one-field first-run screen: no company at all (409 company_required), or
  // a profile nobody has named yet (a fresh self-hosted install).
  const firstSetup = noCompany || initialSetupRequired === true;

  async function loadCompanyProfile() {
    try {
      setLoading(true);
      setError('');
      const response = await api.get<CompanyProfile>('/company/');
      const data = response.data;
      setNoCompany(false);
      if (initialSetupRequired === null) {
        setInitialSetupRequired(!isCompanyConfigured(data));
      }
      setCompanyId(data.id);
      setSavedGstin(data.gst || '');
      setSavedCurrency(data.currency_code || '');
      const loaded: CompanyProfileUpdate = {
        name: data.name || '',
        address: data.address || '',
        gst: data.gst || '',
        pan: data.pan || (data.gst ? data.gst.slice(2, 12) : ''),
        tan: data.tan || '',
        enable_purchase_tds: data.enable_purchase_tds || false,
        phone_number: data.phone_number || '',
        currency_code: companyFormCurrency(data.currency_code),
        email: data.email || '',
        website: data.website || '',
        show_sku_on_pdf: data.show_sku_on_pdf || false,
        default_pdf_paper: data.default_pdf_paper || 'a4',
        eway_enabled: data.eway_enabled ?? true,
        eway_local_threshold: data.eway_local_threshold ?? 50000,
        eway_interstate_threshold: data.eway_interstate_threshold ?? 50000,
        eway_always_show_button: data.eway_always_show_button ?? true,
        show_pay_qr_on_invoice: data.show_pay_qr_on_invoice || false,
        show_upi_pay_button: data.show_upi_pay_button || false,
        enable_tcs: data.enable_tcs || false,
      };
      setForm(loaded);
      if (loaded.gst) setGstOpen(true);
      setSavedForm(loaded);
      setAdditionalInfo(data.additional_company_info || '');
      if (data.logo_data && data.logo_mime_type) {
        setLogoUrl(`data:${data.logo_mime_type};base64,${data.logo_data}`);
      } else {
        setLogoUrl(null);
      }
    } catch (err) {
      if (axios.isAxiosError(err) && err.response?.status === 409 && getApiErrorCode(err) === 'company_required') {
        setNoCompany(true);
        setCompanyId(0);
        const draft = readSetupDraft<CompanyProfileUpdate>(useAuthStore.getState().userEmail);
        if (draft) setForm((current) => ({ ...current, ...draft }));
        if (draft?.gst?.trim()) setGstOpen(true);
        if (initialSetupRequired === null) {
          setInitialSetupRequired(true);
        }
      } else {
        setError(getApiErrorMessage(err, 'Unable to load company profile'));
      }
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadCompanyProfile();
  }, []);

  useEffect(() => {
    if (!loading && !noCompany && searchParams.get('focus') === 'address') {
      addressInputRef.current?.focus();
      addressInputRef.current?.scrollIntoView({ block: 'center' });
    }
  }, [loading, noCompany, searchParams]);

  // Until the first company is saved, keep what has been typed for this tab.
  const setupDraftOwner = useAuthStore((state) => state.userEmail);
  useEffect(() => {
    if (noCompany) writeSetupDraft(setupDraftOwner, form);
  }, [noCompany, form, setupDraftOwner]);

  // First setup starts with the account's name (Google name, or the one confirmed
  // at email sign-up), unless a draft already has a name or the person has typed.
  // /auth/me may answer after the profile, so this waits for both.
  const accountFullName = useAuthStore((state) => state.fullName);
  useEffect(() => {
    if (loading || !firstSetup || !accountFullName || nameEditedRef.current) return;
    setForm((current) => {
      const name = pickSetupNamePrefill(accountFullName, setupDraftOwner, current.name);
      return name === current.name ? current : { ...current, name };
    });
  }, [loading, firstSetup, accountFullName, setupDraftOwner]);

  // Any invoice at all, cancelled and purchase vouchers included: each of them
  // was issued in the currency the company had then. If the check fails we warn
  // anyway, since staying silent is the worse mistake.
  async function companyHasInvoices(): Promise<boolean> {
    try {
      const response = await api.get<{ total: number }>('/invoices/', {
        params: { page: 1, page_size: 1, show_cancelled: true },
      });
      return response.data.total > 0;
    } catch {
      return true;
    }
  }

  function checkGstinBeforeSave() {
    if (invalidGst) {
      setGstTouched(true);
      gstInputRef.current?.focus();
      gstInputRef.current?.scrollIntoView({ block: 'center' });
    }
    return invalidGst;
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    // Every blank required field at once, under the field, with the first in view.
    const missing = missingCompanyFields(form);
    setMissingFields(missing);
    const firstMissing = missing.name ? nameInputRef.current : missing.address ? addressInputRef.current : null;
    if (firstMissing) {
      firstMissing.focus();
      firstMissing.scrollIntoView({ block: 'center' });
      return;
    }
    if (checkGstinBeforeSave()) {
      pendingNavRef.current = null;
      return;
    }

    if (isCurrencyChange(savedCurrency, form.currency_code)) {
      setSubmitting(true);
      const hasInvoices = await companyHasInvoices();
      setSubmitting(false);
      if (hasInvoices) {
        setShowCurrencyWarning(true);
        return;
      }
    }
    await saveCompany();
  }

  function buildPayload(): CompanyProfileUpdate {
    return {
      name: form.name.trim(),
      address: form.address.trim(),
      gst: normalizeGstinInput(form.gst),
      pan: (form.pan || '').trim().toUpperCase(),
      tan: (form.tan || '').trim().toUpperCase(),
      // Never send the setting on without a TAN: the server refuses that save.
      enable_purchase_tds: purchaseTdsSetting(form.enable_purchase_tds, form.tan),
      phone_number: form.phone_number.trim(),
      currency_code: form.currency_code.trim().toUpperCase(),
      email: form.email.trim(),
      website: form.website.trim(),
      show_sku_on_pdf: form.show_sku_on_pdf,
      default_pdf_paper: form.default_pdf_paper,
      eway_enabled: form.eway_enabled,
      eway_local_threshold: form.eway_local_threshold,
      eway_interstate_threshold: form.eway_interstate_threshold,
      eway_always_show_button: form.eway_always_show_button,
      show_pay_qr_on_invoice: form.show_pay_qr_on_invoice,
      show_upi_pay_button: form.show_upi_pay_button,
      enable_tcs: form.enable_tcs,
    };
  }

  /**
   * "Start billing" on the first-run screen (#963). Save always answers: an
   * empty name is shown under the field with no request and no toast; while
   * waiting the button says "Starting…"; it cannot send twice; and a failed
   * request says so under the button with the typed values kept.
   */
  async function handleFirstSetupSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (setupGuard.busy) return;
    setSetupSaveError('');

    const missing = missingCompanyFields(form, false);
    setMissingFields(missing);
    if (missing.name) {
      nameInputRef.current?.focus();
      nameInputRef.current?.scrollIntoView({ block: 'nearest' });
      return;
    }
    if (checkGstinBeforeSave()) return;

    if (!setupGuard.claim()) return;
    setSubmitting(true);
    const payload = buildPayload();
    try {
      if (noCompany) {
        // First company for this user: the creator becomes its admin and the
        // new company becomes their active one. `first_setup` makes a second
        // (or stale) tab get the company back instead of a second one (#1151).
        const created = await api.post<CompanyProfile>('/company/companies', payload, {
          params: { first_setup: true },
        });
        localStorage.setItem('active_company_id', String(created.data.id));
      } else {
        // A profile that exists but was never named (a fresh self-hosted install).
        await api.put<CompanyProfileUpdate>('/company/', payload);
      }
    } catch (err) {
      setupGuard.release();
      setSubmitting(false);
      if (isConnectionOrServerError(err)) {
        setSetupSaveError(SAVE_FAILED_MESSAGE);
        return;
      }
      const { message, fieldErrors } = await getApiErrorDetails(err, 'Unable to save company profile');
      const errors = companyIdentityErrors(fieldErrors);
      if (errors.gst) {
        // A GSTIN the server refused goes under the GSTIN field, opened if need be.
        setGstOpen(true);
        setIdentityErrors(errors);
        window.requestAnimationFrame(() => gstInputRef.current?.focus());
        return;
      }
      setSetupSaveError(message);
      return;
    }

    // The company exists now. Nothing below may send the person back to the form:
    // a second tap would create a second company.
    clearSetupDraft(useAuthStore.getState().userEmail);
    try {
      // The creator's role only exists now; without this they would look like a
      // non-admin until the next page load.
      await useAuthStore.getState().hydrateUserRole();
      // The FY list was loaded at sign-in, when the API still answered 409 (no
      // company). The backend has now seeded an active FY, so reload it.
      await useFYStore.getState().refreshFYList();
      await queryClient.invalidateQueries({ queryKey: ['company-setup-required'] });
      await queryClient.invalidateQueries({ queryKey: ['sidebar-companies'] });
      await queryClient.invalidateQueries({ queryKey: ['company', 'profile'] });
    } catch {
      /* Each of these reloads on its own later; the company is saved either way. */
    }
    // Straight into the composer with the walkthrough running: no "Company
    // created" dialog in between. Someone who cannot add products goes to the dashboard.
    if (canStartTour(useAuthStore.getState().companyRole)) {
      useFirstInvoiceTourStore.getState().start();
      navigate(INVOICE_PATH);
    } else {
      navigate('/');
    }
    // The guard and the busy state stay set: this page is on its way out.
  }

  async function saveCompany() {
    try {
      setSubmitting(true);
      setError('');
      setSuccess('');

      await api.put<CompanyProfileUpdate>('/company/', buildPayload());
      // The sidebar reads enable_tcs from this query to show the TCS page.
      await queryClient.invalidateQueries({ queryKey: ['company-setup-required'] });
      setSuccess('Company profile saved. New invoices will now show this as billing company.');
      await queryClient.invalidateQueries({ queryKey: ['company', 'profile'] });
      setIdentityErrors({});
      await loadCompanyProfile();
      const next = pendingNavRef.current;
      pendingNavRef.current = null;
      if (next) navigate(next);
    } catch (err) {
      pendingNavRef.current = null;
      const { message, fieldErrors } = await getApiErrorDetails(err, 'Unable to save company profile');
      setError(message);
      showIdentityErrors(fieldErrors);
    } finally {
      setSubmitting(false);
    }
  }

  /** Puts GSTIN / PAN / TAN errors under their inputs and brings the first into view. */
  function showIdentityErrors(fieldErrors: Parameters<typeof companyIdentityErrors>[0]) {
    const errors = companyIdentityErrors(fieldErrors);
    setIdentityErrors(errors);
    const first = firstIdentityErrorField(errors);
    const input = first === 'gst' ? gstInputRef.current : first === 'pan' ? panInputRef.current : first === 'tan' ? tanInputRef.current : null;
    // The button is at the foot of a long form, so on a phone the field is off-screen.
    input?.focus();
    input?.scrollIntoView({ block: 'center' });
  }

  async function handleAdditionalInfoSave(value: string) {
    const gstMessage = checkGstinBeforeSave();
    if (gstMessage) throw new Error(gstMessage);
    setAdditionalSaving(true);
    try {
      const payload: CompanyProfileUpdate = {
        ...form,
        gst: normalizeGstinInput(form.gst),
        additional_company_info: value,
      };
      await api.put('/company/', payload);
      setAdditionalInfo(value);
    } catch (err) {
      // This save sends the whole form, so an unsaved bad PAN or TAN fails it too:
      // point at that field as well as reporting under this card.
      showIdentityErrors((await getApiErrorDetails(err, 'Failed to save')).fieldErrors);
      throw err;
    } finally {
      setAdditionalSaving(false);
    }
  }

  const formDirty = isCompanyFormDirty(savedForm, form);

  const addressInput = (
    <>
      <textarea
        id="company-address"
        ref={addressInputRef}
        className="textarea"
        value={form.address}
        onChange={(event) => {
          setMissingFields((current) => ({ ...current, address: undefined }));
          setForm((current) => ({ ...current, address: event.target.value }));
        }}
        autoComplete="street-address"
        required
        aria-invalid={missingFields.address ? true : undefined}
        aria-describedby={missingFields.address ? 'company-address-error' : 'company-address-hint'}
      />
      {missingFields.address
        ? <p className="field-error" id="company-address-error" role="alert">{missingFields.address}</p>
        : <small className="field-hint" id="company-address-hint">Printed on every invoice, e.g. 14 Laxmi Road, Pune 411030.</small>}
    </>
  );

  if (firstSetup || (loading && setupRequiredByRoute)) {
    return (
      <FirstBusinessSetup
        loading={loading}
        name={form.name}
        onNameChange={(name) => {
          nameEditedRef.current = true;
          setMissingFields((current) => ({ ...current, name: undefined }));
          setForm((current) => ({ ...current, name }));
        }}
        nameError={missingFields.name}
        gst={form.gst}
        onGstChange={(gst) => {
          setIdentityErrors((current) => ({ ...current, gst: undefined }));
          setForm((current) => ({ ...current, gst }));
        }}
        onGstBlur={() => setGstTouched(true)}
        gstError={gstError}
        gstOpen={gstOpen}
        onOpenGst={() => {
          setGstOpen(true);
          // The field replaces the link; put the caret in it once it is there.
          window.requestAnimationFrame(() => gstInputRef.current?.focus());
        }}
        busy={submitting}
        saveError={setupSaveError}
        onSubmit={handleFirstSetupSubmit}
        nameInputRef={nameInputRef}
        gstInputRef={gstInputRef}
      />
    );
  }

  return (
    <div className="page-grid">
      <section className="page-hero">
        <div>
          <p className="eyebrow">Company</p>
          <h1 className="page-title">Billing identity</h1>
          <p className="section-copy">Set the company details, branding, and legal terms that appear on invoices and other documents.</p>
        </div>
      </section>

      <StatusToasts error={error} success={success} onClearError={() => setError('')} onClearSuccess={() => setSuccess('')} />

      {leaveTarget ? (
        <ConfirmDialog
          title="Save your changes?"
          message="You have changed your company details. Save them before opening Cash & Bank Accounts, or stay here and keep editing."
          confirmText="Save and open"
          cancelText="Stay here"
          confirmDisabled={submitting}
          onCancel={() => setLeaveTarget(null)}
          onConfirm={() => {
            pendingNavRef.current = leaveTarget;
            setLeaveTarget(null);
            formRef.current?.requestSubmit();
          }}
        />
      ) : null}

      {showCurrencyWarning ? (
        <CurrencyChangeDialog
          fromCurrency={savedCurrency}
          toCurrency={form.currency_code.trim().toUpperCase()}
          confirmDisabled={submitting}
          onCancel={() => {
            setShowCurrencyWarning(false);
            pendingNavRef.current = null;
            setForm((current) => ({ ...current, currency_code: savedCurrency }));
          }}
          onConfirm={async () => {
            await saveCompany();
            setShowCurrencyWarning(false);
          }}
        />
      ) : null}

      {/* -------- Branding Section (Logo + Additional Info) -------- */}
      {!loading && (
        <section className="content-grid content-grid--single">
          <article className="panel stack" style={{ gap: '24px' }}>
            <LogoUploadCard logoUrl={logoUrl} onLogoChanged={loadCompanyProfile} />
            <AdditionalInfoSection
              value={additionalInfo}
              onSave={handleAdditionalInfoSave}
              saving={additionalSaving}
            />
          </article>
        </section>
      )}

      <section className="content-grid">
        <article className="panel stack">
          <div className="panel__header">
            <div>
              <p className="eyebrow">Company setup</p>
              <h2 className="nav-panel__title">Invoice header details</h2>
            </div>
          </div>
          {loading ? <div className="empty-state">Loading company profile...</div> : null}

          {/* No example values as placeholders: grey "Simple Invoicing Pvt Ltd" and
              "12 MG Road" read as already filled in, and new users pressed Save on an
              empty form. Examples go in the hint under the field instead.
              noValidate: the required fields are checked in handleSubmit, all at once. */}
          {!loading ? (
            <form ref={formRef} className="stack" onSubmit={handleSubmit} noValidate>
              <small className="field-hint">Fields marked <span style={{ color: 'var(--color-danger)' }}>*</span> are required.</small>
              <div className="field-grid">
                <div className="field">
                  <label htmlFor="company-name">Company name <span style={{ color: 'var(--color-danger)' }} aria-hidden="true">*</span></label>
                  <input
                    id="company-name"
                    ref={nameInputRef}
                    className="input"
                    value={form.name}
                    onChange={(event) => {
                      setMissingFields((current) => ({ ...current, name: undefined }));
                      setForm((current) => ({ ...current, name: event.target.value }));
                    }}
                    autoComplete="organization"
                    required
                    aria-invalid={missingFields.name ? true : undefined}
                    aria-describedby={missingFields.name ? 'company-name-error' : 'company-name-hint'}
                  />
                  {missingFields.name
                    ? <p className="field-error" id="company-name-error" role="alert">{missingFields.name}</p>
                    : <small className="field-hint" id="company-name-hint">As it should appear on your invoices, e.g. Sharma Traders.</small>}
                </div>

                <div className="field">
                  <label htmlFor="company-gst">GSTIN</label>
                  <GstinInput
                    id="company-gst"
                    ref={gstInputRef}
                    className="input"
                    value={form.gst}
                    onValueChange={(gst) => {
                      setIdentityErrors((current) => ({ ...current, gst: undefined }));
                      setForm((current) => ({ ...current, gst }));
                    }}
                    onBlur={() => setGstTouched(true)}
                    autoCapitalize="characters"
                    aria-invalid={gstError ? true : undefined}
                    aria-describedby={gstError ? 'company-gst-error' : undefined}
                  />
                  <small className="field-hint">Format: 27ABCDE1234F1Z0</small>
                  {gstError ? <p className="field-error" id="company-gst-error" role="alert">{gstError}</p> : null}
                </div>

                <div className="field">
                  <label htmlFor="company-pan">PAN</label>
                  <input
                    id="company-pan"
                    ref={panInputRef}
                    className="input"
                    value={form.pan || ''}
                    onChange={(event) => {
                      setIdentityErrors((current) => ({ ...current, pan: undefined }));
                      setForm((current) => ({ ...current, pan: event.target.value.toUpperCase() }));
                    }}
                    placeholder="ABCDE1234F"
                    maxLength={10}
                    aria-invalid={identityErrors.pan ? true : undefined}
                    aria-describedby={identityErrors.pan ? 'company-pan-error' : undefined}
                  />
                  {identityErrors.pan ? <p className="field-error" id="company-pan-error" role="alert">{identityErrors.pan}</p> : null}
                </div>

                <div className="field">
                  <label htmlFor="company-tan">TAN</label>
                  <input
                    id="company-tan"
                    ref={tanInputRef}
                    className="input"
                    value={form.tan || ''}
                    onChange={(event) => {
                      setIdentityErrors((current) => ({ ...current, tan: undefined }));
                      const tan = event.target.value.toUpperCase();
                      // Emptying the TAN turns purchase TDS off: it cannot stay on without one.
                      setForm((current) => ({ ...current, tan, enable_purchase_tds: tan.trim() ? current.enable_purchase_tds : false }));
                    }}
                    placeholder="ABCD12345E"
                    maxLength={10}
                    aria-invalid={identityErrors.tan ? true : undefined}
                    aria-describedby={identityErrors.tan ? 'company-tan-error' : undefined}
                  />
                  {identityErrors.tan ? <p className="field-error" id="company-tan-error" role="alert">{identityErrors.tan}</p> : null}
                </div>

                <div className="field field--full">
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '8px' }}>
                    <input
                      id="company-enable-purchase-tds"
                      type="checkbox"
                      checked={Boolean(form.enable_purchase_tds) && Boolean((form.tan || '').trim())}
                      disabled={!(form.tan || '').trim()}
                      onChange={(e) => setForm((current) => ({ ...current, enable_purchase_tds: e.target.checked }))}
                    />
                    <label htmlFor="company-enable-purchase-tds" style={{ marginBottom: 0, cursor: 'pointer', fontWeight: 500 }}>
                      Deduct TDS on payments to suppliers
                    </label>
                  </div>
                  {!(form.tan || '').trim() ? (
                    <small className="field-hint" style={{ marginLeft: '24px' }}>Enter the company TAN first.</small>
                  ) : null}
                  <small className="field-hint" style={{ marginLeft: '24px' }}>
                    Is your business required to deduct TDS? Companies, firms, LLPs, trusts and societies must deduct TDS on contractor, professional, commission and rent payments (a 'specified' or 'designated' person under the Income-tax Act 2025). An individual or HUF must do so only if their turnover last year was above ₹1 crore (business) or ₹50 lakh (profession). TDS on purchase of goods (s.393(1) Sl. No. 8(ii), formerly 194Q) applies only if your turnover last year was above ₹10 crore, and only on purchases above ₹50 lakh from one seller in the tax year.
                  </small>
                  {form.enable_purchase_tds && (form.tan || '').trim() ? (
                    <small className="field-hint" style={{ marginLeft: '24px' }}>
                      <Link to="/tds?tab=payable">View the TDS report</Link>
                    </small>
                  ) : null}
                </div>

                <div className="field">
                  <label htmlFor="company-phone">Phone number</label>
                  <input
                    id="company-phone"
                    className="input"
                    value={form.phone_number}
                    onChange={(event) => setForm((current) => ({ ...current, phone_number: event.target.value }))}
                  />
                  <small className="field-hint">e.g. +91 98765 43210</small>
                </div>

                <div className="field">
                  <label htmlFor="company-currency">Currency</label>
                  <select
                    id="company-currency"
                    className="select"
                    value={form.currency_code}
                    onChange={(event) => setForm((current) => ({ ...current, currency_code: event.target.value }))}
                  >
                    <option value="INR">INR - Indian Rupee</option>
                    <option value="USD">USD - US Dollar</option>
                    <option value="EUR">EUR - Euro</option>
                    <option value="GBP">GBP - British Pound</option>
                    <option value="AED">AED - UAE Dirham</option>
                  </select>
                </div>

                <div className="field">
                  <label htmlFor="company-email">Email</label>
                  <input
                    id="company-email"
                    className="input"
                    value={form.email}
                    onChange={(event) => setForm((current) => ({ ...current, email: event.target.value }))}
                  />
                </div>

                <div className="field">
                  <label htmlFor="company-website">Website</label>
                  <input
                    id="company-website"
                    className="input"
                    value={form.website}
                    onChange={(event) => setForm((current) => ({ ...current, website: event.target.value }))}
                  />
                </div>

                <div className="field field--full">
                  <label htmlFor="company-address">Address <span style={{ color: 'var(--color-danger)' }} aria-hidden="true">*</span></label>
                  {addressInput}
                </div>

                <div className="field field--full">
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '8px' }}>
                    <input
                      id="company-show-sku-pdf"
                      type="checkbox"
                      checked={form.show_sku_on_pdf}
                      onChange={(e) => setForm((current) => ({ ...current, show_sku_on_pdf: e.target.checked }))}
                    />
                    <label htmlFor="company-show-sku-pdf" style={{ marginBottom: 0, cursor: 'pointer', fontWeight: 500 }}>
                      Show SKU column on invoice PDFs
                    </label>
                  </div>
                  <small className="field-hint" style={{ marginLeft: '24px' }}>
                    When disabled, SKU is hidden and the item description gets more horizontal space.
                  </small>
                </div>

                <div className="field">
                  <label htmlFor="company-default-paper">Default paper size</label>
                  <select
                    id="company-default-paper"
                    value={form.default_pdf_paper}
                    onChange={(e) => setForm((current) => ({ ...current, default_pdf_paper: e.target.value as PdfPaper }))}
                  >
                    {(Object.keys(PAPER_LABELS) as PdfPaper[]).map((paper) => (
                      <option key={paper} value={paper}>{PAPER_LABELS[paper]}</option>
                    ))}
                  </select>
                  <small className="field-hint">
                    The paper used for downloads, emails and share links. Thermal applies to bills, receipts, notes, challans and quotations; reports fall back to A4.
                  </small>
                </div>

                <div className="field field--full">
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '8px' }}>
                    <input
                      id="company-show-pay-qr"
                      type="checkbox"
                      checked={form.show_pay_qr_on_invoice}
                      onChange={(e) => setForm((current) => ({ ...current, show_pay_qr_on_invoice: e.target.checked }))}
                    />
                    <label htmlFor="company-show-pay-qr" style={{ marginBottom: 0, cursor: 'pointer', fontWeight: 500 }}>
                      Show pay-online QR on invoice PDFs
                    </label>
                  </div>
                  {/* Both consequences are stated because neither is guessable: the QR
                      only works if the invoice has a public link, so printing starts
                      creating one -- and revoking that link later kills the QR on
                      paper already in a customer's hands. */}
                  <small className="field-hint" style={{ marginLeft: '24px' }}>
                    Adds a QR that opens a page where the customer can pay you by UPI. Printing an
                    invoice creates a shareable link for it; revoking that link later stops the QR on
                    copies already printed from working. Add a UPI ID under Cash &amp; Bank Accounts
                    for the payment option to appear.
                  </small>
                </div>

                <div className="field field--full">
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '8px' }}>
                    <input
                      id="company-show-upi-pay-button"
                      type="checkbox"
                      checked={form.show_upi_pay_button}
                      onChange={(e) => setForm((current) => ({ ...current, show_upi_pay_button: e.target.checked }))}
                    />
                    <label htmlFor="company-show-upi-pay-button" style={{ marginBottom: 0, cursor: 'pointer', fontWeight: 500 }}>
                      Show &ldquo;Pay by UPI&rdquo; button on shared invoices
                    </label>
                  </div>
                  {/* The merchant caveat is the whole reason this is a setting: for a
                      personal UPI ID the tap-to-pay hand-off draws a risk warning in
                      apps like Paytm, and nothing here can tell which kind was entered. */}
                  <small className="field-hint" style={{ marginLeft: '24px' }}>
                    Adds a tap-to-pay button, with Google Pay, PhonePe and Paytm shortcuts, above the
                    UPI QR on a shared invoice or statement. Turn this on only if your UPI ID is
                    registered as a merchant with your UPI provider &mdash; with a personal UPI ID, apps
                    such as Paytm warn your customer that the payment may fail. The QR keeps working
                    either way.
                  </small>
                </div>

                <div className="field field--full">
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '8px' }}>
                    <input
                      id="company-enable-tcs"
                      type="checkbox"
                      checked={form.enable_tcs}
                      onChange={(e) => setForm((current) => ({ ...current, enable_tcs: e.target.checked }))}
                    />
                    <label htmlFor="company-enable-tcs" style={{ marginBottom: 0, cursor: 'pointer', fontWeight: 500 }}>
                      Collect TCS on sales invoices
                    </label>
                  </div>
                  <small className="field-hint" style={{ marginLeft: '24px' }}>
                    Only for sellers of scrap, liquor, minerals, forest produce, motor vehicles or notified goods above ₹10 lakh. Ordinary sales do not attract TCS.
                  </small>
                </div>

                <div className="field field--full">
                  {/* A text link, not a button: as a button beside Save it drew the
                      click meant for Save, and leaving dropped the edits. */}
                  <small className="field-hint">
                    Your bank accounts, cash accounts and UPI ID are kept in{' '}
                    <Link
                      to={CASH_BANK_PATH}
                      className="link-button"
                      onClick={(event) => {
                        if (!formDirty) return;
                        event.preventDefault();
                        setLeaveTarget(CASH_BANK_PATH);
                      }}
                    >
                      Cash &amp; Bank Accounts &rarr;
                    </Link>
                  </small>
                </div>
              </div>

              <div className={`form-save-bar${formDirty ? ' form-save-bar--dirty' : ''}`}>
                <button
                  className="button button--primary"
                  disabled={submitting || !formDirty}
                  title="Save company details"
                  aria-label="Save company details"
                >
                  {submitting ? 'Saving company...' : 'Save company details'}
                </button>
                <span className="form-save-bar__status" role="status">
                  {formDirty ? 'You have unsaved changes' : 'All changes saved'}
                </span>
              </div>
            </form>
          ) : null}
        </article>

        {/* Terms & Conditions */}
        {!loading && companyId > 0 && (
          <TermsAndConditionsCard companyId={companyId} />
        )}

        {/* E-Way Bill Settings */}
        {!loading && (
          <EWayBillSettingsCard
            form={form}
            onChange={(patch) => setForm((current) => ({ ...current, ...patch }))}
          />
        )}

        <InvoiceSeriesCard sectionRef={seriesSectionRef} savedGstin={savedGstin} />
      </section>
    </div>
  );
}
