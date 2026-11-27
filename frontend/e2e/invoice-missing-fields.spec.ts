import { test, expect, selectComboboxOption, clickNavLink, createProduct, adjustInventory, uniqueSku, uniqueGstin, expectSuccess, chooseVoucherType } from './fixtures';

const EXPECT_TIMEOUT = Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000');

/* The Create invoice button used to stay disabled until every required field
   was filled, without saying which one was missing. Now it is always enabled,
   and a click marks each missing field with its own message. */
test.describe('Create invoice with missing fields', () => {
  test('marks each missing field, clears it once filled, then saves', async ({ authedPage: page }) => {
    const sku = uniqueSku();
    const ledgerName = `Missing Fields Ledger ${sku}`;

    await clickNavLink(page, '/catalogue');
    await createProduct(page, { sku, name: `Missing Fields ${sku}`, price: '250', gstRate: '18' });
    await adjustInventory(page, sku, '5');

    await clickNavLink(page, '/ledgers');
    await page.click('button:has-text("Create ledger")');
    await page.fill('#ledger-name', ledgerName);
    await page.fill('#ledger-address', '1 Test Street');
    await page.fill('#ledger-gst', uniqueGstin());
    await page.fill('#ledger-phone', '+91 9000000003');
    await page.click('button:has-text("Create ledger")');
    await expectSuccess(page, 'Ledger created');

    await clickNavLink(page, '/invoices');
    await expect(page.locator('#invoice-ledger')).not.toBeDisabled({ timeout: EXPECT_TIMEOUT });
    await chooseVoucherType(page, 'sales');

    const createButton = page.getByRole('button', { name: 'Create invoice', exact: true });
    await expect(createButton).toBeEnabled();
    await page.waitForTimeout(800);

    // Nothing chosen yet: both the ledger and the product are marked.
    await createButton.click();
    const ledger = page.locator('#invoice-ledger');
    const product = page.locator('#invoice-product-1');
    await expect(ledger).toHaveAttribute('aria-invalid', 'true');
    await expect(page.locator('#invoice-ledger-error')).toHaveText('Choose or add a customer first');
    await expect(product).toHaveAttribute('aria-invalid', 'true');
    await expect(page.locator('#invoice-product-1-error')).toHaveText('Pick a product from the list');
    // The strip by the button names the first problem and counts the rest.
    const reason = page.locator('.composer-submit__reason');
    await expect(reason).toHaveText('Choose a customer, and 1 more to fix.');
    // The page scrolls to the first missing field.
    await expect(ledger).toBeInViewport();
    await page.waitForTimeout(1500);

    // Choosing the ledger clears its mark; the product stays marked.
    await selectComboboxOption(page, 'invoice-ledger', ledgerName);
    await expect(ledger).not.toHaveAttribute('aria-invalid', 'true');
    await expect(page.locator('#invoice-ledger-error')).toHaveCount(0);
    await expect(product).toHaveAttribute('aria-invalid', 'true');
    await expect(reason).toHaveText('Pick a product for line 1.');
    await page.waitForTimeout(1000);

    // An empty quantity is caught too.
    await selectComboboxOption(page, 'invoice-product-1', sku);
    const quantity = page.locator('#invoice-quantity-1');
    await quantity.fill('');
    await page.waitForTimeout(500);
    await createButton.click();
    await expect(quantity).toHaveAttribute('aria-invalid', 'true');
    await expect(page.locator('#invoice-quantity-1-error')).toHaveText('Enter a quantity');
    await expect(reason).toHaveText('Enter a quantity for line 1.');
    await expect(quantity).toBeFocused();
    await expect(product).not.toHaveAttribute('aria-invalid', 'true');
    await page.waitForTimeout(1500);

    await quantity.fill('2');
    await expect(quantity).not.toHaveAttribute('aria-invalid', 'true');
    await expect(reason).toHaveCount(0);
    await page.waitForTimeout(800);
    await createButton.click();
    await expectSuccess(page, 'Sales invoice created');

    const preview = page.locator('.modal-panel--invoice-preview');
    await expect(preview).toBeVisible({ timeout: 10_000 });
    await page.waitForTimeout(1500);
  });
});
