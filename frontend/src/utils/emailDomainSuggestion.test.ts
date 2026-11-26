import { describe, expect, it } from 'vitest';
import { levenshtein, suggestEmailDomain } from './emailDomainSuggestion';

describe('levenshtein', () => {
  it('counts edits', () => {
    expect(levenshtein('gmail.com', 'gmail.com')).toBe(0);
    expect(levenshtein('gmail.con', 'gmail.com')).toBe(1);
    expect(levenshtein('gmial.com', 'gmail.com')).toBe(2);
    expect(levenshtein('', 'abc')).toBe(3);
  });
});

describe('suggestEmailDomain', () => {
  it('suggests nothing for the listed domains', () => {
    for (const d of ['gmail.com', 'yahoo.com', 'outlook.com', 'hotmail.com', 'yahoo.co.in', 'rediffmail.com']) {
      expect(suggestEmailDomain(`someone@${d}`)).toBeNull();
    }
  });

  it('corrects common typos', () => {
    expect(suggestEmailDomain('someone@gmaui.com')).toBe('someone@gmail.com');
    expect(suggestEmailDomain('someone@gmial.com')).toBe('someone@gmail.com');
    expect(suggestEmailDomain('someone@yahho.com')).toBe('someone@yahoo.com');
    expect(suggestEmailDomain('someone@hotmial.com')).toBe('someone@hotmail.com');
    expect(suggestEmailDomain('someone@gmail.con')).toBe('someone@gmail.com');
    expect(suggestEmailDomain('someone@outlook.co')).toBe('someone@outlook.com');
  });

  it('suggests nothing for unrelated domains', () => {
    expect(suggestEmailDomain('someone@company.in')).toBeNull();
    expect(suggestEmailDomain('someone@example.org')).toBeNull();
  });

  it('leaves real providers near a listed domain alone', () => {
    expect(suggestEmailDomain('someone@ymail.com')).toBeNull();
    expect(suggestEmailDomain('someone@gmx.com')).toBeNull();
    expect(suggestEmailDomain('someone@yahoo.co.uk')).toBeNull();
    expect(suggestEmailDomain('someone@live.com')).toBeNull();
  });

  it('ignores case and surrounding spaces, and keeps the local part', () => {
    expect(suggestEmailDomain('  Some.One+tag@GMAUI.COM  ')).toBe('Some.One+tag@gmail.com');
    expect(suggestEmailDomain('Someone@GMAIL.com')).toBeNull();
  });

  it('waits for a complete address', () => {
    for (const v of ['', 'someone', 'someone@', '@gmaui.com', 'someone@gmail', 'someone@gmail.c']) {
      expect(suggestEmailDomain(v)).toBeNull();
    }
  });

  it('allows only one edit on short domains', () => {
    expect(suggestEmailDomain('a@gmx.co')).toBeNull();
  });
});
