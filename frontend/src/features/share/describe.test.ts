import { afterEach, describe, expect, it, vi } from 'vitest';
import { describeShareLinkPeriod, describeViews } from './describe';
import type { ShareLink } from '../../types/api';

function link(overrides: Partial<ShareLink>): ShareLink {
  return {
    id: 1,
    token: 'tok',
    url: 'https://example.test/s/tok',
    resource_type: 'ledger_statement',
    resource_id: 7,
    from_date: null,
    to_date: null,
    view_count: 0,
    last_viewed_at: null,
    created_at: '2026-11-01T00:00:00Z',
    ...overrides,
  };
}

describe('describeShareLinkPeriod', () => {
  it('shows both dates for a dated link as DD-MM-YYYY', () => {
    expect(describeShareLinkPeriod(link({ from_date: '2026-10-01', to_date: '2026-10-31' })))
      .toBe('01-10-2026 to 31-10-2026');
  });

  it('names the open-ended reminder link Always current', () => {
    expect(describeShareLinkPeriod(link({ from_date: null, to_date: null })))
      .toBe('Always current (payment reminders)');
  });

  it('labels a partially dated link from what it has', () => {
    expect(describeShareLinkPeriod(link({ from_date: '2026-10-01', to_date: null })))
      .toBe('From 01-10-2026');
    expect(describeShareLinkPeriod(link({ from_date: null, to_date: '2026-10-31' })))
      .toBe('Until 31-10-2026');
  });
});

describe('describeViews', () => {
  it('reports an unopened link', () => {
    expect(describeViews(0, null)).toBe('Not opened yet');
  });

  it('singularises a single opening', () => {
    expect(describeViews(1, null)).toBe('Opened once');
  });

  it('counts several openings', () => {
    expect(describeViews(4, null)).toBe('Opened 4 times');
  });

  describe('last opened time', () => {
    afterEach(() => {
      vi.useRealTimers();
      vi.unstubAllEnvs();
    });

    it.each([
      '2026-11-22T21:25:39.259550',
      '2026-11-22T21:25:39Z',
      '2026-11-23T02:55:39+05:30',
      '2026-11-22T16:25:39-05:00',
    ])('shows the elapsed time for %s in Asia/Kolkata', (timestamp) => {
      vi.stubEnv('TZ', 'Asia/Kolkata');
      vi.useFakeTimers();
      vi.setSystemTime(new Date('2026-11-22T21:26:09Z'));

      const elapsed = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' }).format(-30, 'second');
      expect(describeViews(4, timestamp)).toBe(`Opened 4 times · last ${elapsed}`);
    });
  });
});
