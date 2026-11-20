export function pageAfterOutOfRange(page: number,totalPages: number): number | null {
  return totalPages >= 1 && page > totalPages ? totalPages : null;
}
