import { afterEach, describe, expect, it, vi } from 'vitest';
import api from './client';
import { fetchAllLedgers, fetchAllProducts } from './lookups';
import type { Ledger, Product } from '../types/api';

const ledger = (id: number, name: string) => ({ id, name }) as Ledger;
const product = (id: number, name: string) => ({ id, name }) as Product;

/** A list endpoint holding `rows`, answering `page_size` rows a page as the server does. */
function serve<T>(rows: T[]) {
  return vi.spyOn(api, 'get').mockImplementation(async (_url, config) => {
    const { page, page_size: pageSize } = (config?.params ?? {}) as { page: number; page_size: number };
    const items = rows.slice((page - 1) * pageSize, page * pageSize);
    return { data: { items, total: rows.length, page, page_size: pageSize, total_pages: Math.ceil(rows.length / pageSize) } };
  });
}

describe('fetchAllLedgers', () => {
  afterEach(() => vi.restoreAllMocks());

  it('reaches ledgers past the first 500, so Cash & Bank can name them (#921)', async () => {
    const rows = Array.from({ length: 520 }, (_, index) =>
      ledger(index + 1, `Customer ${String(index + 1).padStart(3, '0')}`),
    );
    const get = serve(rows);

    const ledgers = await fetchAllLedgers();

    expect(ledgers).toHaveLength(520);
    expect(ledgers.find((entry) => entry.id === 510)?.name).toBe('Customer 510');
    expect(get.mock.calls.map(([url, config]) => [url, config?.params])).toEqual([
      ['/ledgers/', { page: 1, page_size: 500 }],
      ['/ledgers/', { page: 2, page_size: 500 }],
    ]);
  });

  it('asks once when every ledger fits on one page', async () => {
    const get = serve([ledger(1, 'Only')]);

    expect(await fetchAllLedgers()).toEqual([ledger(1, 'Only')]);
    expect(get).toHaveBeenCalledTimes(1);
  });
});

describe('fetchAllProducts', () => {
  afterEach(() => vi.restoreAllMocks());

  it('reaches products past the first 500, so the Analytics product filter can offer them', async () => {
    const rows = Array.from({ length: 501 }, (_, index) => product(index + 1, `Item ${index + 1}`));
    const get = serve(rows);

    const products = await fetchAllProducts();

    expect(products.map((entry) => entry.id)).toEqual(rows.map((entry) => entry.id));
    expect(get).toHaveBeenCalledWith('/products/', { params: { page: 2, page_size: 500 } });
  });
});
