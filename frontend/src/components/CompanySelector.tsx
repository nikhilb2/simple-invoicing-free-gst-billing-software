import { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import axios from 'axios';
import { useQuery } from '@tanstack/react-query';
import { AnimatePresence, motion } from 'framer-motion';
import api, { getApiErrorMessage } from '../api/client';
import ModalCloseButton from './ModalCloseButton';
import { useEscapeClose } from '../hooks/useEscapeClose';
import { GSTIN_LENGTH, gstinError } from '../utils/gstin';
import GstinInput from './GstinInput';
import type {
  CompanyCreationCapOut,
  CompanyListItem,
  CompanyProfile,
  CompanyProfileUpdate,
  CompanySelectOut,
} from '../types/api';

export default function CompanySelector({ onDialogOpen, onDialogClose }: {
  onDialogOpen?: () => void;
  onDialogClose?: () => void;
}) {
  const [companyDropdownOpen, setCompanyDropdownOpen] = useState(false);
  const [companySwitchingId, setCompanySwitchingId] = useState<number | null>(null);
  const [companyError, setCompanyError] = useState('');
  const [newCompanyModalOpen, setNewCompanyModalOpen] = useState(false);

  useEscapeClose(useCallback(() => setNewCompanyModalOpen(false), []));
  const [newCompanyName, setNewCompanyName] = useState('');
  const [nameError, setNameError] = useState('');
  const nameInputRef = useRef<HTMLInputElement>(null);
  const switcherRef = useRef<HTMLButtonElement>(null);
  const [newCompanyGst, setNewCompanyGst] = useState('');
  const [gstTouched, setGstTouched] = useState(false);
  const gstInputRef = useRef<HTMLInputElement>(null);
  const invalidGst = gstinError(newCompanyGst);
  const gstError = gstTouched || newCompanyGst.length >= GSTIN_LENGTH ? invalidGst : null;
  const [newCompanySubmitting, setNewCompanySubmitting] = useState(false);
  const [newCompanyError, setNewCompanyError] = useState('');
  const companyDropdownRef = useRef<HTMLDivElement>(null);

  const companiesQuery = useQuery({
    queryKey: ['sidebar-companies'],
    queryFn: async () => {
      const [companiesRes, capabilityRes] = await Promise.all([
        api.get<CompanyListItem[]>('/company/companies'),
        api.get<CompanyCreationCapOut>('/company/companies/capability'),
      ]);

      return {
        companies: companiesRes.data,
        canCreateCompany: capabilityRes.data.can_create_company,
      };
    },
    refetchOnWindowFocus: 'always',
  });

  const companyList = companiesQuery.data?.companies ?? [];
  const canCreateCompany = companiesQuery.data?.canCreateCompany ?? false;
  const activeCompany = companyList.find((company) => company.is_active) ?? null;
  // A 401 means the session ended and the visitor is being sent to sign in;
  // the API's "Not authenticated" is not something to show them.
  const queryError = companiesQuery.error && !(axios.isAxiosError(companiesQuery.error) && companiesQuery.error.response?.status === 401)
    ? getApiErrorMessage(companiesQuery.error, 'Failed to load companies')
    : '';
  const effectiveCompanyError = companyError || queryError;

  useEffect(() => {
    if (!companyDropdownOpen) return;
    const onClickOutside = (e: MouseEvent) => {
      if (companyDropdownRef.current && !companyDropdownRef.current.contains(e.target as Node)) {
        setCompanyDropdownOpen(false);
      }
    };
    document.addEventListener('mousedown', onClickOutside);
    return () => document.removeEventListener('mousedown', onClickOutside);
  }, [companyDropdownOpen]);

  const handleCompanySwitch = async (companyId: number) => {
    if (companySwitchingId !== null) return;
    setCompanySwitchingId(companyId);
    setCompanyError('');
    try {
      const res = await api.post<CompanySelectOut>(`/company/select/${companyId}`);
      localStorage.setItem('active_company_id', String(res.data.active_company_id));
      window.location.reload();
    } catch (error) {
      setCompanyError(getApiErrorMessage(error, 'Failed to switch company'));
    } finally {
      setCompanySwitchingId(null);
    }
  };

  const handleCreateCompany = async () => {
    if (newCompanySubmitting) return;
    const trimmedName = newCompanyName.trim();
    if (!trimmedName) {
      setNameError('Enter your business name');
      nameInputRef.current?.focus();
      return;
    }
    if (invalidGst) {
      setNewCompanyError('');
      setGstTouched(true);
      gstInputRef.current?.focus();
      return;
    }
    setNewCompanySubmitting(true);
    setNewCompanyError('');
    const payload: CompanyProfileUpdate = {
      name: trimmedName,
      address: '',
      gst: newCompanyGst,
      phone_number: '',
      currency_code: 'INR',
      email: '',
      website: '',
      bank_name: '',
      branch_name: '',
      account_name: '',
      account_number: '',
      ifsc_code: '',
    };

    try {
      const createRes = await api.post<CompanyProfile>('/company/companies', payload);
      await handleCompanySwitch(createRes.data.id);
    } catch (error) {
      setNewCompanyError(getApiErrorMessage(error, 'Failed to create company'));
    } finally {
      setNewCompanySubmitting(false);
    }
  };

  return (
    <>
      <p className="sidebar__group-label" style={{ marginBottom: '6px' }}>Company</p>
      <div ref={companyDropdownRef} style={{ position: 'relative', marginBottom: '12px' }}>
        <button
          className="button button--ghost"
          data-testid="company-switcher"
          ref={switcherRef}
          style={{ width: '100%', textAlign: 'left', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
          onClick={() => setCompanyDropdownOpen((v) => !v)}
          aria-haspopup="listbox"
          aria-expanded={companyDropdownOpen}
        >
          <span style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {activeCompany?.name?.trim() || 'Select company'}
          </span>
          <span style={{ fontSize: '0.75rem', opacity: 0.8 }}>▾</span>
        </button>
        {companyDropdownOpen && (
          <div
            role="listbox"
            style={{
              position: 'absolute',
              left: 0,
              right: 0,
              top: 'calc(100% + 4px)',
              background: 'var(--bg-card-strong)',
              border: '1px solid var(--line-strong)',
              borderRadius: '0.75rem',
              boxShadow: '0 4px 24px rgb(var(--rgb-shadow) / 0.45)',
              zIndex: 100,
              overflow: 'hidden',
              color: 'var(--text)',
            }}
          >
            {companiesQuery.isLoading && (
              <p style={{ padding: '0.5rem 0.75rem', fontSize: '0.85rem', opacity: 0.7 }}>Loading companies...</p>
            )}
            {!companiesQuery.isLoading && companyList.length === 0 && (
              <p style={{ padding: '0.5rem 0.75rem', fontSize: '0.85rem', opacity: 0.8 }}>No companies found</p>
            )}
            {companyList.map((company) => (
              <button
                key={company.id}
                role="option"
                aria-selected={company.is_active}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.5rem',
                  width: '100%',
                  textAlign: 'left',
                  padding: '0.5rem 0.75rem',
                  background: 'none',
                  border: 'none',
                  cursor: companySwitchingId === null ? 'pointer' : 'wait',
                  fontWeight: company.is_active ? 700 : 500,
                  fontSize: '0.875rem',
                  color: 'inherit',
                }}
                disabled={companySwitchingId !== null}
                onClick={() => {
                  void handleCompanySwitch(company.id);
                  setCompanyDropdownOpen(false);
                }}
              >
                <span style={{ width: '1rem' }}>{company.is_active ? '✓' : ''}</span>
                {company.name || `Company #${company.id}`}
              </button>
            ))}
            {canCreateCompany && (
              <>
                <hr style={{ margin: '0.25rem 0', border: 'none', borderTop: '1px solid var(--line)' }} />
                <button
                  style={{
                    display: 'block',
                    width: '100%',
                    textAlign: 'left',
                    padding: '0.5rem 0.75rem',
                    background: 'none',
                    border: 'none',
                    cursor: 'pointer',
                    fontSize: '0.875rem',
                    color: 'inherit',
                    fontWeight: 500,
                  }}
                  onClick={() => {
                    setCompanyDropdownOpen(false);
                    setNewCompanyName('');
                    setNameError('');
                    setNewCompanyGst('');
                    setGstTouched(false);
                    setNewCompanyError('');
                    setNewCompanyModalOpen(true);
                    onDialogOpen?.();
                  }}
                >
                  + New Company
                </button>
              </>
            )}
          </div>
        )}
      </div>
      {effectiveCompanyError && (
        <p style={{ marginTop: '-6px', marginBottom: '8px', color: 'var(--error)', fontSize: '0.8rem' }}>
          {effectiveCompanyError}
        </p>
      )}

      {/* The mobile sidebar is transformed, so fixed dialogs must live outside it. */}
      {createPortal(<AnimatePresence onExitComplete={() => {
        onDialogClose?.();
        requestAnimationFrame(() => switcherRef.current?.focus({ preventScroll: true }));
      }}>
        {newCompanyModalOpen && (
          <motion.div
            className="modal-overlay"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            onClick={(e) => { if (e.target === e.currentTarget) setNewCompanyModalOpen(false); }}
          >
            <motion.div
              className="modal-panel new-company-dialog"
              role="dialog"
              aria-modal="true"
              aria-labelledby="new-company-title"
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              transition={{ duration: 0.2 }}
              style={{ maxWidth: '28rem' }}
            >
              <div className="panel__header">
                <h2 className="nav-panel__title" id="new-company-title">New company</h2>
                <ModalCloseButton onClick={() => setNewCompanyModalOpen(false)} label="Close new company" />
              </div>
              <form noValidate onSubmit={(event) => { event.preventDefault(); void handleCreateCompany(); }} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                <div className="field">
                  <label htmlFor="new-company-name">Business name <span aria-hidden="true">*</span></label>
                  <input
                    id="new-company-name"
                    ref={nameInputRef}
                    className="input"
                    value={newCompanyName}
                    onChange={(e) => { setNewCompanyName(e.target.value); setNameError(''); }}
                    placeholder="e.g. Sharma General Store"
                    required
                    aria-invalid={nameError ? true : undefined}
                    aria-describedby={nameError ? 'new-company-name-error' : undefined}
                    autoFocus
                  />
                  {nameError && <p className="field-error" id="new-company-name-error" role="alert">{nameError}</p>}
                </div>
                <label style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem', fontSize: '0.875rem', fontWeight: 500 }}>
                  GSTIN (optional)
                  <GstinInput
                    className="input"
                    ref={gstInputRef}
                    value={newCompanyGst}
                    onValueChange={setNewCompanyGst}
                    onBlur={() => setGstTouched(true)}
                    placeholder="27ABCDE1234F1Z0"
                    aria-invalid={gstError ? true : undefined}
                    aria-describedby={gstError ? 'new-company-gst-error' : undefined}
                  />
                </label>
                {gstError && <p className="field-error" id="new-company-gst-error" role="alert">{gstError}</p>}
                <p style={{ margin: 0, fontSize: '0.8rem', opacity: 0.7 }}>
                  You can complete the GSTIN, address and bank details on the Company page.
                </p>
                {newCompanyError && <p style={{ margin: 0, color: 'var(--error)', fontSize: '0.85rem' }}>{newCompanyError}</p>}
                <div className="new-company-actions">
                  <button
                    type="submit"
                    className="button button--primary"
                    disabled={newCompanySubmitting}
                  >
                    {newCompanySubmitting ? 'Creating…' : 'Create company'}
                  </button>
                  <button type="button" className="button button--ghost" onClick={() => setNewCompanyModalOpen(false)}>
                    Cancel
                  </button>
                </div>
              </form>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>, document.body)}
    </>
  );
}
