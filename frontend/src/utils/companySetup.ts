import axios from 'axios';
import type { CompanyProfile } from '../types/api';

export const COMPANY_SETUP_PATH = '/settings/company?setup=required';
export const COMPANY_ADDRESS_PATH = '/settings/company?focus=address';

export function hasCompanyAddress(company: Pick<CompanyProfile, 'address'> | null | undefined): boolean {
  return Boolean(company?.address?.trim());
}

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
export function missingCompanyFields(form: { name: string; address: string }, requireAddress = true): MissingCompanyFields {
  const missing: MissingCompanyFields = {};
  if (!form.name.trim()) missing.name = 'Enter your business name.';
  if (requireAddress && !form.address.trim()) missing.address = 'Enter your business address. It is printed on every invoice.';
  return missing;
}

/**
 * What the Business name field starts with on the first-run screen (#963).
 *
 * A setup draft the person already typed wins. Otherwise the account's name from
 * /auth/me: the Google account name, or the name confirmed at email sign-up. The
 * backend falls back to the email address when there is no name, and an email
 * is not a business name, so that leaves the field empty.
 */
export function pickSetupNamePrefill(
  fullName: string | null | undefined,
  email: string | null | undefined,
  draftName: string | null | undefined,
): string {
  if (draftName?.trim()) return draftName;
  const name = (fullName ?? '').trim();
  if (!name) return '';
  if (email && name.toLowerCase() === email.trim().toLowerCase()) return '';
  return name;
}

/**
 * How a settings route that does not need a company behaves while there is none.
 *
 * `frame`: the company page, drawn in the setup-only frame (brand, Sign out,
 * help) instead of the app with its sidebar and settings sub-navigation.
 * `redirect`: the settings overview and Appearance, which used to let a new user
 * wander away from setup; they send them to it instead.
 */
export type SetupRouteMode = 'frame' | 'redirect';

export function setupRouteAction(mode: SetupRouteMode, setupRequired: boolean): 'app' | 'setup-frame' | 'redirect' {
  if (!setupRequired) return 'app';
  return mode === 'frame' ? 'setup-frame' : 'redirect';
}
