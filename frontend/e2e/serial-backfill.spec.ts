import type { Page } from '@playwright/test';
import { test, expect, uniqueSku, catalogueSearch, showMoreProductOptions } from './fixtures';

async function apiRequest<T>(page: Page, method: string, path: string, body?: unknown): Promise<T> {
  return page.evaluate(async ({ method, path, body }) => {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    const token = localStorage.getItem('token');
    const companyId = localStorage.getItem('active_company_id');
    if (token) headers.Authorization = `Bearer ${token}`;
    if (companyId) headers['X-Company-Id'] = companyId;
    const response = await fetch(`/api${path}`, {
      method, headers, body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!response.ok) throw new Error(`${method} ${path}: ${response.status} ${await response.text()}`);
    return response.json();
  }, { method, path, body });
}

async function seedUntrackedStock(page: Page, serialCount: number, stock: number) {
  const sku = uniqueSku();
  const payload = { sku, name: `Serial backfill ${sku}`, price: 100, gst_rate: 0, maintain_inventory: true };
  const serials = Array.from({ length: serialCount }, (_, index) => `${sku}-${String(index).padStart(3, '0')}`);
  const product = await apiRequest<{ id: number }>(page, 'POST', '/products/', {
    ...payload, track_serials: true, initial_quantity: serialCount, serial_numbers: serials,
  });
  await apiRequest(page, 'PUT', `/products/${product.id}`, { ...payload, track_serials: false });
  if (stock !== serialCount) {
    await apiRequest(page, 'POST', '/inventory/adjust', {
      product_id: product.id, quantity: stock - serialCount, note: 'E2E units moved while serial tracking was off',
    });
  }
  return { ...payload, id: product.id, serials };
}

async function openBackfill(page: Page, product: { name: string; sku: string }) {
  await page.goto('/catalogue');
  await catalogueSearch(page).fill(product.sku);
  await page.getByRole('button', { name: `All settings for ${product.name}`, exact: true }).click();
  const form = page.getByRole('dialog', { name: `Editing ${product.name}`, exact: true });
  await showMoreProductOptions(form);
  await form.getByRole('checkbox', { name: 'Track individual serial numbers / IMEIs' }).check();
  await form.getByRole('button', { name: 'Save changes', exact: true }).click();
}

async function serialsWithStatus(page: Page, productId: number, status: string) {
  return apiRequest<{ total: number; items: Array<{ serial_number: string }> }>(
    page, 'GET', `/serials/?product_id=${productId}&status=${status}&page_size=500`,
  );
}

test.describe('Re-enabling serial tracking', () => {
  test('keeps the chosen serials across pages and searches, then writes off only the rest', async ({ authedPage: page }) => {
    const product = await seedUntrackedStock(page, 51, 2);
    await openBackfill(page, product);
    const dialog = page.getByRole('dialog', { name: 'Choose the serials still in stock' });
    await expect(dialog).toContainText('The other 49 will be written off');
    const save = dialog.getByRole('button', { name: 'Turn on serial tracking', exact: true });
    await expect(save).toBeDisabled();
    await dialog.getByRole('checkbox', { name: product.serials[0], exact: true }).check();
    await expect(save).toBeDisabled();
    await dialog.getByRole('button', { name: 'Next', exact: true }).click();
    await dialog.getByRole('checkbox', { name: product.serials[50], exact: true }).check();
    await expect(save).toBeEnabled();
    await dialog.getByRole('searchbox', { name: 'Search serials to keep' }).fill(product.serials[1]);
    await dialog.getByRole('checkbox', { name: product.serials[1], exact: true }).check();
    await expect(save).toBeDisabled();
    await dialog.getByRole('button', { name: `Remove serial ${product.serials[0]}`, exact: true }).click();
    await expect(save).toBeEnabled();

    // A server-side refusal must leave the selection available for correction.
    await page.route(`**/api/products/${product.id}`, (route) => route.fulfill({
      status: 400, json: { detail: 'Stock changed. Check the serials and try again.' },
    }));
    await save.click();
    await expect(dialog.getByRole('alert')).toContainText('Stock changed.');
    await expect(dialog.getByRole('list', { name: 'Selected serials' }).getByRole('listitem')).toHaveCount(2);
    await page.unroute(`**/api/products/${product.id}`);

    const request = page.waitForRequest((req) => req.method() === 'PUT' && req.url().endsWith(`/products/${product.id}`));
    await save.click();
    expect((await request).postDataJSON().serial_numbers).toEqual([product.serials[50], product.serials[1]]);
    await expect(dialog).toBeHidden();
    const kept = await serialsWithStatus(page, product.id, 'in_stock');
    expect(kept.items.map((row) => row.serial_number).sort()).toEqual([product.serials[1], product.serials[50]]);
    expect((await serialsWithStatus(page, product.id, 'void')).total).toBe(49);
  });

  test('cancel keeps tracking off and leaves all serial records in stock', async ({ authedPage: page }) => {
    const product = await seedUntrackedStock(page, 3, 1);
    await openBackfill(page, product);
    const dialog = page.getByRole('dialog', { name: 'Choose the serials still in stock' });
    await dialog.getByRole('checkbox', { name: product.serials[1], exact: true }).check();
    await dialog.getByRole('button', { name: 'Cancel serial tracking', exact: true }).click();
    await expect(dialog).toBeHidden();
    expect((await serialsWithStatus(page, product.id, 'in_stock')).total).toBe(3);
    const products = await apiRequest<{ items: Array<{ id: number; track_serials: boolean }> }>(page, 'GET', `/products/?search=${product.sku}`);
    expect(products.items.find((row) => row.id === product.id)?.track_serials).toBe(false);
  });

  test('zero stock explains that every old serial will be written off', async ({ authedPage: page }) => {
    const product = await seedUntrackedStock(page, 3, 0);
    await openBackfill(page, product);
    const dialog = page.getByRole('dialog', { name: 'Choose the serials still in stock' });
    await expect(dialog).toContainText('The other 3 will be written off');
    await expect(dialog).toContainText('0 selected to keep');
    await dialog.getByRole('button', { name: 'Turn on serial tracking', exact: true }).click();
    await expect(dialog).toBeHidden();
    expect((await serialsWithStatus(page, product.id, 'in_stock')).total).toBe(0);
    expect((await serialsWithStatus(page, product.id, 'void')).total).toBe(3);
  });

  test('ordinary backfill still registers new serials for uncovered stock', async ({ authedPage: page }) => {
    const product = await seedUntrackedStock(page, 1, 3);
    await openBackfill(page, product);
    const dialog = page.getByRole('dialog', { name: 'Enter the serials already in stock' });
    await expect(dialog).toContainText('Enter the IMEI for the remaining 2');
    const newSerials = [`${product.sku}-NEW-1`, `${product.sku}-NEW-2`];
    await dialog.getByLabel('Or paste a list').fill(newSerials.join('\n'));
    await dialog.getByRole('button', { name: 'Add pasted serials', exact: true }).click();
    await dialog.getByRole('button', { name: 'Turn on serial tracking', exact: true }).click();
    await expect(dialog).toBeHidden();
    const kept = await serialsWithStatus(page, product.id, 'in_stock');
    expect(kept.items.map((row) => row.serial_number).sort()).toEqual([...product.serials, ...newSerials].sort());
    expect((await serialsWithStatus(page, product.id, 'void')).total).toBe(0);
  });
});
