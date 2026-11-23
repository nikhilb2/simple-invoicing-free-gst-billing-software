import { describe, expect, it, test } from 'vitest';
import type { CompanyProfile } from '../types/api';
import { clearSetupDraft, companyFormCurrency, isCompanyConfigured, missingCompanyFields, isCompanyFormDirty, isCompanySetupRequired, readSetupDraft, writeSetupDraft } from './companySetup';

describe('company form currency', () => {
  test.each([null, undefined, ''])('defaults a missing currency (%s) to INR', (currency) => {
    expect(companyFormCurrency(currency)).toBe('INR');
  });

  test.each(['USD', 'EUR', 'INR'])('keeps an explicitly saved %s', (currency) => {
    expect(companyFormCurrency(currency)).toBe(currency);
  });
});

describe('isCompanySetupRequired', () => {
  const conflict = Object.assign(new Error('x'), {
    isAxiosError: true,
    response: { status: 409, data: { detail: { code: 'company_required' } } },
  });

  test('required on a company_required conflict', () => {
    expect(isCompanySetupRequired(undefined, conflict)).toBe(true);
  });
  test('required for a profile with no name', () => {
    expect(isCompanySetupRequired({ name: ' ' } as CompanyProfile, null)).toBe(true);
  });
  test('not required once a company is named', () => {
    expect(isCompanySetupRequired({ name: 'Acme' } as CompanyProfile, null)).toBe(false);
  });
  test('does not block while loading or on unrelated failures', () => {
    expect(isCompanySetupRequired(undefined, null, true)).toBe(false);
    expect(isCompanySetupRequired(undefined, new Error('network'))).toBe(false);
  });
});

describe('isCompanyConfigured — falsey or incomplete profiles are not configured', () => {
  test('null profile', () => {
    expect(isCompanyConfigured(null)).toBe(false);
  });

  test('undefined profile', () => {
    expect(isCompanyConfigured(undefined)).toBe(false);
  });

  test('empty company name', () => {
    const profile = { name: '' } as CompanyProfile;
    expect(isCompanyConfigured(profile)).toBe(false);
  });

  test('whitespace-only company name', () => {
    const profile = { name: '   ' } as CompanyProfile;
    expect(isCompanyConfigured(profile)).toBe(false);
  });

  test('profile object without name property', () => {
    const profile = {} as unknown as CompanyProfile;
    expect(isCompanyConfigured(profile)).toBe(false);
  });
});

describe('isCompanyConfigured — valid profiles are configured', () => {
  test('profile with a real company name', () => {
    const profile = { name: 'Acme Corporation' } as CompanyProfile;
    expect(isCompanyConfigured(profile)).toBe(true);
  });

  test('profile with leading and trailing whitespace around name', () => {
    const profile = { name: '  Global Logistics Ltd  ' } as CompanyProfile;
    expect(isCompanyConfigured(profile)).toBe(true);
  });
});

describe('company setup draft', () => {
  function memoryStorage() {
    const data = new Map<string, string>();
    return {
      getItem: (key: string) => data.get(key) ?? null,
      setItem: (key: string, value: string) => void data.set(key, value),
      removeItem: (key: string) => void data.delete(key),
    };
  }

  test('a saved draft comes back for the same person only', () => {
    const storage = memoryStorage();
    writeSetupDraft('a@example.com', { name: 'Sonu Bags', address: 'Main road' }, storage);
    expect(readSetupDraft('a@example.com', storage)).toEqual({ name: 'Sonu Bags', address: 'Main road' });
    expect(readSetupDraft('b@example.com', storage)).toBeNull();
  });

  test('clearing it, or having no signed-in person, gives nothing back', () => {
    const storage = memoryStorage();
    writeSetupDraft('a@example.com', { name: 'X' }, storage);
    clearSetupDraft('a@example.com', storage);
    expect(readSetupDraft('a@example.com', storage)).toBeNull();
    writeSetupDraft(null, { name: 'X' }, storage);
    expect(readSetupDraft(null, storage)).toBeNull();
  });

  test('a corrupt or unreadable draft is ignored, not thrown', () => {
    const storage = memoryStorage();
    storage.setItem('company_setup_draft:a@example.com', '{not json');
    expect(readSetupDraft('a@example.com', storage)).toBeNull();
    storage.setItem('company_setup_draft:a@example.com', '[1,2]');
    expect(readSetupDraft('a@example.com', storage)).toBeNull();
    const broken = { getItem: () => { throw new Error('blocked'); }, setItem: () => { throw new Error('full'); }, removeItem: () => { throw new Error('blocked'); } };
    expect(readSetupDraft('a@example.com', broken)).toBeNull();
    expect(() => writeSetupDraft('a@example.com', { name: 'X' }, broken)).not.toThrow();
    expect(() => clearSetupDraft('a@example.com', broken)).not.toThrow();
  });
});

describe('isCompanyFormDirty', () => {
  const saved = { name: 'Sharma Electricals', address: 'Pune', show_sku_on_pdf: false };
  it('is clean when nothing changed', () => {
    expect(isCompanyFormDirty(saved, { ...saved })).toBe(false);
  });
  it('sees a typed change', () => {
    expect(isCompanyFormDirty(saved, { ...saved, address: 'Pune 411030' })).toBe(true);
  });
  it('sees a ticked box', () => {
    expect(isCompanyFormDirty(saved, { ...saved, show_sku_on_pdf: true })).toBe(true);
  });
  it('is clean before the profile has loaded', () => {
    expect(isCompanyFormDirty(null, saved)).toBe(false);
  });
});

describe('missingCompanyFields', () => {
  test('names every blank required field at once', () => {
    expect(missingCompanyFields({ name: '', address: '  ' })).toEqual({
      name: 'Enter your business name.',
      address: 'Enter your business address. It is printed on every invoice.',
    });
  });
  test('only the field that is blank', () => {
    expect(Object.keys(missingCompanyFields({ name: 'Rao Traders', address: '' }))).toEqual(['address']);
  });
  test('nothing missing once both are filled', () => {
    expect(missingCompanyFields({ name: 'Rao Traders', address: '1 MG Road, Pune' })).toEqual({});
  });
});
