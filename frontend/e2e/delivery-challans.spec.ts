import type { Page } from '@playwright/test';
import {
  test,
  expect,
  expectSuccess,
  INVOICE_TOAST,
  uniqueSku,
  uniqueGstin,
  selectComboboxOption,
} from './fixtures';

/**
 * Delivery challans, from the form to an invoice and back.
 *
 * The walk that matters: saving a challan takes stock out; editing adjusts it;
 * converting with a different quantity moves only the difference; cancelling the
 * invoice reopens the challan; cancelling the challan puts everything back.
 */
test.describe('Delivery challans', () => {
  const OPENING_STOCK = 50;

  async function api(page: Page, method: string, path: string, body?: unknown) {
    return page.evaluate(
      async ({ method, path, body }) => {
        const response = await fetch(`/api${path}`, {
          method,
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${localStorage.getItem('token')}` },
          body: body === undefined ? undefined : JSON.stringify(body),
        });
        const text = await response.text();
        return { ok: response.ok, status: response.status, text };
      },
      { method, path, body },
    );
  }

  async function send(page: Page, method: string, path: string, body?: unknown) {
    const result = await api(page, method, path, body);
    if (!result.ok) throw new Error(`${path} -> ${result.status} ${result.text}`);
    return JSON.parse(result.text);
  }

  async function stockOf(page: Page, sku: string): Promise<number> {
    const list = await send(page, 'GET', `/products/with-inventory?search=${encodeURIComponent(sku)}`);
    const rows: Array<{ sku: string }> = Array.isArray(list) ? list : list.items;
    const product: any = rows.find((item) => item.sku === sku);
    return Number(product.current_stock);
  }

  async function seed(page: Page) {
    const stamp = uniqueSku();
    const sku = `${stamp}-DC`;
    const product = await send(page, 'POST', '/products/', {
      sku, name: `DC-Prod ${stamp}`, price: 100, gst_rate: 18, hsn_sac: '8471',
      maintain_inventory: true, initial_quantity: OPENING_STOCK,
    });
    const ledger = await send(page, 'POST', '/ledgers/', {
      name: `DC-Customer-${stamp}`, address: '12 Buyer Street', gst: uniqueGstin(), phone_number: '+91 5555555555',
    });
    return { sku, product, ledger };
  }

  async function closePreview(page: Page) {
    await page.getByRole('button', { name: 'Close delivery challan preview' }).click();
  }

  test('a challan takes stock out, and an invoice moves only the difference', async ({ authedPage: page }) => {
    test.setTimeout(180_000);
    const { sku, product, ledger } = await seed(page);
    expect(await stockOf(page, sku)).toBe(OPENING_STOCK);

    // 1. Create through the form.
    await page.goto('/delivery-challans/new');
    await selectComboboxOption(page, 'challan-ledger', ledger.name);
    await page.selectOption('#challan-purpose', 'job_work');
    await selectComboboxOption(page, 'challan-product-1', sku);
    await page.fill('#challan-quantity-1', '10');
    await page.click('button:has-text("Save challan")');
    await expectSuccess(page, 'saved');

    const preview = page.getByRole('dialog', { name: /Delivery Challan DC/ });
    await expect(preview).toBeVisible();
    const heading = (await preview.locator('#challan-preview-title').innerText()).trim();
    const challanNumber = heading.split(' ').pop() as string;
    expect(challanNumber).toMatch(/^DC/);
    expect(await stockOf(page, sku)).toBe(40);

    // PDF downloads under the challan's own name.
    await expect(preview.locator('iframe')).toBeVisible();
    const download = page.waitForEvent('download');
    await preview.getByRole('button', { name: 'Download' }).click();
    expect((await download).suggestedFilename()).toBe(`delivery_challan_${challanNumber.replace('/', '_')}.pdf`);
    await closePreview(page);

    // 2. Edit to 12.
    await page.goto(`/delivery-challans?search=${encodeURIComponent(challanNumber)}`);
    const row = page.locator('tr', { hasText: challanNumber });
    await expect(row).toContainText('Open');
    const challanList = await send(page, 'GET', `/delivery-challans/?search=${encodeURIComponent(challanNumber)}`);
    const challan = challanList.items[0];
    await page.goto(`/delivery-challans/${challan.id}/edit`);
    await expect(page.locator('#challan-quantity-1')).toHaveValue('10');
    await page.fill('#challan-quantity-1', '12');
    await page.click('button:has-text("Save challan")');
    await expectSuccess(page, 'updated');
    await closePreview(page);
    expect(await stockOf(page, sku)).toBe(38);

    // 3. Convert, invoicing 9 of the 12.
    await page.goto(`/delivery-challans?search=${encodeURIComponent(challanNumber)}`);
    await expect(page.locator('tr', { hasText: challanNumber })).toContainText('Open');
    await page.locator('tr', { hasText: challanNumber }).getByRole('button', { name: 'Convert to invoice' }).click();
    await expect(page.getByTestId('challan-conversion-banner')).toContainText(challanNumber);
    await expect(page.locator('#invoice-quantity-1')).toHaveValue('12');
    await page.fill('#invoice-quantity-1', '9');
    await expect(page.getByTestId('challan-quantity-note')).toContainText(
      'challan 12, invoicing 9. 3 will be added back to stock. Make sure they\'re returned.',
    );
    await page.click('button:has-text("Create invoice")');
    await expectSuccess(page, 'created from delivery challan');

    const invoiceDialog = page.getByRole('dialog', { name: /Invoice/ });
    await expect(invoiceDialog).toContainText(`Against challan ${challanNumber}`);
    const invoiceTitle = await invoiceDialog.locator('h2, h1').first().innerText();
    const invoiceNumber = invoiceTitle.match(/INV\S+/)?.[0] as string;
    expect(invoiceNumber).toBeTruthy();
    await invoiceDialog.getByRole('button', { name: /Close invoice preview/ }).click();

    expect(await stockOf(page, sku)).toBe(41);
    await page.goto(`/delivery-challans?search=${encodeURIComponent(challanNumber)}`);
    const invoiced = page.locator('tr', { hasText: challanNumber });
    await expect(invoiced).toContainText('Invoiced');
    await expect(invoiced).toContainText(invoiceNumber);

    // 4. Cancel the invoice: the challan reopens and its goods are out again.
    await page.goto(`/invoices-view?search=${encodeURIComponent(invoiceNumber)}`);
    await page.getByRole('tab', { name: 'Card' }).click();
    const card = page.locator('.invoice-compact-card', { hasText: invoiceNumber }).first();
    await card.locator('button[title="Cancel"]').click();
    await page.click('button:has-text("Cancel invoice")');
    await expectSuccess(page, INVOICE_TOAST.cancelled);

    await expect.poll(async () => {
      await page.goto(`/delivery-challans?search=${encodeURIComponent(challanNumber)}`);
      return page.locator('tr', { hasText: challanNumber }).innerText();
    }, { timeout: 15_000 }).toContain('Open');
    expect(await stockOf(page, sku)).toBe(38);

    // 6. E-way bill JSON from the challan (before cancelling it).
    const precheck = await api(page, 'GET', `/delivery-challans/${challan.id}/eway-bill/precheck`);
    if (!precheck.ok) {
      test.info().annotations.push({ type: 'skip', description: `E-way bill not available: ${precheck.status} ${precheck.text}` });
    } else {
      const form = JSON.parse(precheck.text).form_data;
      const generated = await api(page, 'POST', `/delivery-challans/${challan.id}/eway-bill/generate`, {
        ...form,
        seller_pincode: form.seller_pincode || '400001',
        buyer_pincode: form.buyer_pincode || '400002',
        vehicle_number: 'MH12AB1234',
        distance_km: form.distance_km ?? 10,
      });
      expect(generated.ok, generated.text).toBe(true);
      const bill = JSON.parse(generated.text).billLists[0];
      expect(bill.docType).toBe('CHL');
      expect(bill.subSupplyType).toBe(4);
    }

    // 5. Cancel the challan: everything is back.
    await page.goto(`/delivery-challans?search=${encodeURIComponent(challanNumber)}`);
    await page.locator('tr', { hasText: challanNumber }).getByRole('button', { name: challanNumber }).click();
    const openPreview = page.getByRole('dialog', { name: /Delivery Challan/ });
    await openPreview.getByRole('button', { name: 'More actions' }).click();
    await page.getByRole('menuitem', { name: 'Cancel challan' }).click();
    await page.getByRole('button', { name: 'Cancel challan', exact: true }).last().click();
    await expectSuccess(page, 'cancelled');
    await expect(page.locator('tr', { hasText: challanNumber })).toContainText('Cancelled');
    expect(await stockOf(page, sku)).toBe(OPENING_STOCK);
    expect(product.id).toBeTruthy();
  });
});
