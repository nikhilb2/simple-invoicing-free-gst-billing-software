export function pageAfterOutOfRange(page: number,totalPages: number): number | null {
  return totalPages >= 1 && page > totalPages ? totalPages : null;
}

/** The list endpoints' maximum page_size. */
export const MAX_PAGE_SIZE = 500;

/** One page of items, as a paginated list endpoint returns it. */
export type PaginatedItems<T> = {
  items: T[];
  total_pages: number;
};

/**
 * Every item across all pages, in order.
 *
 * The fetch callback takes the page number and page size and returns one
 * page. A page that comes back empty while the server still claims more
 * pages would otherwise spin this loop forever, so an empty page ends
 * the fetch. Taking the fetch as a callback keeps this testable in Node
 * without a DOM or a network call.
 */
export async function fetchAllPages<T>(
  fetchPage: (page: number, pageSize: number) => Promise<PaginatedItems<T>>,
  pageSize: number = MAX_PAGE_SIZE,
): Promise<T[]> {
  const items: T[] = [];
  let page = 1;
  let totalPages = 1;

  while (page <= totalPages) {
    const res = await fetchPage(page, pageSize);
    totalPages = Math.max(1, res.total_pages);
    if (res.items.length === 0) break;
    items.push(...res.items);
    page += 1;
  }

  return items;
}
