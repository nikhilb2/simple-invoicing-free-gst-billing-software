import type { ApiFieldError } from '../api/client';

/** The identity fields on Company settings that show their own error under the input. */
export type CompanyIdentityField = 'gst' | 'pan' | 'tan';
export type CompanyIdentityErrors = Partial<Record<CompanyIdentityField, string>>;

const IDENTITY_FIELDS: CompanyIdentityField[] = ['gst', 'pan', 'tan'];

/** Picks the GSTIN / PAN / TAN messages out of a failed save, first message per field. */
export function companyIdentityErrors(fieldErrors: ApiFieldError[]): CompanyIdentityErrors {
  const errors: CompanyIdentityErrors = {};
  for (const { field, message } of fieldErrors) {
    const key = field as CompanyIdentityField;
    if (IDENTITY_FIELDS.includes(key) && !errors[key]) errors[key] = message;
  }
  return errors;
}

/** The field to focus after a failed save: the first one in form order. */
export function firstIdentityErrorField(errors: CompanyIdentityErrors): CompanyIdentityField | null {
  return IDENTITY_FIELDS.find((field) => errors[field]) ?? null;
}
