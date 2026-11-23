import axios from 'axios';
import type { CompanyProfile } from '../types/api';

export const COMPANY_SETUP_PATH = '/settings/company?setup=required';

/** Use the GST app's default only when the profile has no saved currency. */
export function companyFormCurrency(currency: string | null | undefined): string {
  return currency || 'INR';
}

export function isCompanyConfigured(company: CompanyProfile | null | undefined): boolean {
  return Boolean(company?.name?.trim());
}

/**
 * Whether the signed-in user still has to create a company. Mirrors the route
 * guard: a 409 company_required, or a profile with no name. While loading, or
 * on any other failure, the user is not treated as blocked.
 */
export function isCompanySetupRequired(
  data: CompanyProfile | null | undefined,
  error: unknown,
  isLoading = false,
): boolean {
  if (isLoading) return false;
  if (
    axios.isAxiosError(error) &&
    error.response?.status === 409 &&
    error.response.data?.detail?.code === 'company_required'
  ) {
    return true;
  }
  if (error) return false;
  return !isCompanyConfigured(data);
}

/**
 * The first-company form, kept for the tab while no company exists. Until one is
 * saved every other page sends you back to setup, so a refresh or a stray link
 * used to bring back an empty form and lose everything typed.
 */
const SETUP_DRAFT_PREFIX = 'company_setup_draft:';

type DraftStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

function sessionStore(): DraftStorage | null {
  try {
    return typeof window === 'undefined' ? null : window.sessionStorage;
  } catch {
    return null;
  }
}

export function readSetupDraft<T extends object>(owner: string | null, storage: DraftStorage | null = sessionStore()): Partial<T> | null {
  if (!owner || !storage) return null;
  try {
    const raw = storage.getItem(SETUP_DRAFT_PREFIX + owner);
    const parsed: unknown = raw ? JSON.parse(raw) : null;
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? (parsed as Partial<T>) : null;
  } catch {
    return null;
  }
}

export function writeSetupDraft(owner: string | null, draft: object, storage: DraftStorage | null = sessionStore()): void {
  if (!owner || !storage) return;
  try {
    storage.setItem(SETUP_DRAFT_PREFIX + owner, JSON.stringify(draft));
  } catch {
    /* Storage full or blocked: the form still works, it just isn't kept. */
  }
}

export function clearSetupDraft(owner: string | null, storage: DraftStorage | null = sessionStore()): void {
  if (!owner || !storage) return;
  try {
    storage.removeItem(SETUP_DRAFT_PREFIX + owner);
  } catch {
    /* Nothing to clear. */
  }
}

/**
 * Whether the company form holds edits that are not saved yet. Before a profile
 * has loaded there is nothing to compare against, so nothing counts as unsaved.
 */
export function isCompanyFormDirty<T extends object>(saved: T | null, current: T): boolean {
  if (!saved) return false;
  const a = saved as Record<string, unknown>;
  const b = current as Record<string, unknown>;
  return Object.keys({ ...a, ...b }).some((key) => a[key] !== b[key]);
}

export type MissingCompanyFields = { name?: string; address?: string };

/**
 * The required company fields left blank, each with the message shown under it.
 * The form checks these itself rather than leaving it to the browser: the
 * browser names one field per Save press, in a bubble that a phone has often
 * scrolled out of view, so to a new user the Save button seemed to do nothing.
 */
export function missingCompanyFields(form: { name: string; address: string }): MissingCompanyFields {
  const missing: MissingCompanyFields = {};
  if (!form.name.trim()) missing.name = 'Enter your business name.';
  if (!form.address.trim()) missing.address = 'Enter your business address. It is printed on every invoice.';
  return missing;
}
