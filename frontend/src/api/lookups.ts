/**
 * Every ledger and every product, for screens that look names up by id or
 * offer them in a picker.
 *
 * The list endpoints return at most 500 rows a page, sorted by name, so one
 * page left out everything after the 500th: Cash & Bank labelled those
 * payments "Unknown ledger" and the Analytics filters could not reach them
 * (#921). These page through the list until total_pages is reached.
 */
import api from './client';
import type { Ledger, PaginatedLedgers, PaginatedProducts, Product } from '../types/api';
import { fetchAllPages } from '../utils/pagination';

/** Every ledger of the company, across all pages, in the server's order. */
export function fetchAllLedgers(): Promise<Ledger[]> {
  return fetchAllPages<Ledger>(async (page, pageSize) => {
    const res = await api.get<PaginatedLedgers>('/ledgers/', { params: { page, page_size: pageSize } });
    return res.data;
  });
}

/** Every product of the company, across all pages, in the server's order. */
export function fetchAllProducts(): Promise<Product[]> {
  return fetchAllPages<Product>(async (page, pageSize) => {
    const res = await api.get<PaginatedProducts>('/products/', { params: { page, page_size: pageSize } });
    return res.data;
  });
}
