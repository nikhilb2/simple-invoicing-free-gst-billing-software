import { describe, expect, it, vi } from 'vitest';
import { fetchAllPages, pageAfterOutOfRange } from './pagination';

describe('pageAfterOutOfRange', () => {
  it('steps back to the last page when a delete empties the current one', () => {
    expect(pageAfterOutOfRange(2, 1)).toBe(1);
  });

  it('jumps to the last page when several pages disappeared', () => {
    expect(pageAfterOutOfRange(5, 3)).toBe(3);
  });

  it('leaves a page that still exists alone', () => {
    expect(pageAfterOutOfRange(2, 2)).toBeNull();
    expect(pageAfterOutOfRange(1, 1)).toBeNull();
  });

  it('leaves a truly empty list alone so its empty state shows', () => {
    expect(pageAfterOutOfRange(2, 0)).toBeNull();
    expect(pageAfterOutOfRange(1, 0)).toBeNull();
  });
});

describe('fetchAllPages', () => {
  it('calls the callback for pages 1..N and joins the items in order', async () => {
    const fetchPage = vi.fn(async (page: number) => ({
      items: [`page-${page}-a`, `page-${page}-b`],
      total_pages: 3,
    }));

    const items = await fetchAllPages<string>(fetchPage, 2);

    expect(items).toEqual([
      'page-1-a',
      'page-1-b',
      'page-2-a',
      'page-2-b',
      'page-3-a',
      'page-3-b',
    ]);
    expect(fetchPage.mock.calls).toEqual([
      [1, 2],
      [2, 2],
      [3, 2],
    ]);
  });

  it('stops at total_pages and does not fetch beyond it', async () => {
    const fetchPage = vi.fn(async () => ({ items: ['only'], total_pages: 1 }));

    expect(await fetchAllPages<string>(fetchPage, 500)).toEqual(['only']);
    expect(fetchPage).toHaveBeenCalledTimes(1);
  });

  it('stops on an empty page even when more pages are claimed', async () => {
    const fetchPage = vi.fn(async (page: number) => ({
      items: page === 1 ? ['first'] : [],
      total_pages: 5,
    }));

    expect(await fetchAllPages<string>(fetchPage, 500)).toEqual(['first']);
    expect(fetchPage).toHaveBeenCalledTimes(2);
  });
});
