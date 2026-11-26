import type { InvoiceItem } from '../../types/api';

/**
 * Products whose lines on an invoice being edited were saved carrying no serial
 * numbers (`serials_applied === false`), because "Track serials" was off then.
 * The backend decides per product, not per line: such a product takes no serials
 * on the edit whatever its quantity, and a product with a line that did carry
 * serials is not in the set (SerialManager.unserialed_products). A line with no
 * record (null) follows the product's current setting.
 */
export function unserialedProductIds(lines: Pick<InvoiceItem, 'product_id' | 'serials_applied'>[]): number[] {
  const carried = new Set(lines.filter((line) => line.serials_applied === true).map((line) => line.product_id));
  return [...new Set(
    lines.filter((line) => line.serials_applied === false && !carried.has(line.product_id)).map((line) => line.product_id),
  )];
}

/**
 * Whether a form line needs serial numbers. Only a line on a product with "Track
 * serials" on, outside quotes, and not one the invoice being edited billed
 * untracked. Pass `unserialed` only while editing; a line moved to another
 * product, or a new line, follows the normal rule.
 */
export function lineNeedsSerials(
  line: { productId: string },
  product: { track_serials?: boolean } | undefined,
  options: { isQuote: boolean; unserialed?: readonly number[] },
): boolean {
  if (options.isQuote || !product?.track_serials) return false;
  return !(options.unserialed ?? []).includes(Number(line.productId));
}
