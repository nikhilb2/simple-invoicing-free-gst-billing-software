import { test, expect, expectSuccess, uniqueGstin } from './fixtures';

test.describe('Company Profile', () => {
  // Company left the main rail in the sidebar redesign — the only way to it in
  // the UI is now Settings -> Company. This is the one test that walks that
  // path; the rest go straight to the URL, since their subject is the form.
  test('is reachable from the sidebar via Settings', async ({ authedPage: page }) => {
    await page.locator('.sidebar__link--settings').click();
    await expect(page).toHaveURL('/settings');

    await page.locator('.settings-nav__link[href="/settings/company"]').click();
    await expect(page).toHaveURL('/settings/company');
    await expect(page.locator('h1')).toContainText('Billing identity');
  });

  test('shows a bad GSTIN before saving and focuses it on a phone', async ({ authedPage: page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/settings/company');
    await expect(page.locator('#company-name')).toBeVisible({ timeout: 5_000 });

    await page.fill('#company-name', 'Bad GSTIN Co');
    await page.fill('#company-address', '1 Check Digit Road');
    const error = page.locator('#company-gst-error');
    await page.fill('#company-gst', '29ABCDE1234F1Z0');
    await expect(error).toContainText('15th character');

    const updates: string[] = [];
    page.on('request', (req) => {
      if (req.method() === 'PUT' && new URL(req.url()).pathname === '/api/company/') updates.push(req.url());
    });
    await page.click('button:has-text("Save company details")');

    await expect(page.locator('#company-gst')).toBeFocused();
    await expect(page.locator('#company-gst')).toBeInViewport();
    expect(updates).toHaveLength(0);

    await page.fill('#company-gst', uniqueGstin('29'));
    await expect(error).toHaveCount(0);
  });

  test('validates the optional GSTIN in the New Company dialog', async ({ authedPage: page }) => {
    await page.route('**/api/company/companies/capability', (route) =>
      route.fulfill({ json: { can_create_company: true } }),
    );
    await page.goto('/settings/company');
    await page.getByTestId('company-switcher').click();
    await page.getByRole('button', { name: '+ New Company' }).click();
    const dialog = page.getByRole('dialog', { name: 'New company' });
    await dialog.getByLabel('Business name').fill('Second company');
    const gst = dialog.getByLabel('GSTIN (optional)');
    const error = dialog.getByRole('alert');

    await gst.fill('27');
    await expect(error).toHaveCount(0);
    await gst.press('Tab');
    await expect(error).toContainText('format');
    await gst.fill('27ABCDE1234F1Z9');
    await expect(error).toContainText('15th character');
    await dialog.getByRole('button', { name: 'Create company' }).click();
    await expect(gst).toBeFocused();
    await gst.fill('');
    await expect(error).toHaveCount(0);
  });

  test('saves company profile', async ({ authedPage: page }) => {
    await page.goto('/settings/company');

    // Wait for form to be ready
    await expect(page.locator('#company-name')).toBeVisible({ timeout: 5_000 });

    await page.fill('#company-name', 'E2E Test Company Pvt Ltd');
    await page.fill('#company-address', '42 Playwright Avenue, Bangalore');
    await page.fill('#company-gst', uniqueGstin('29'));
    await page.fill('#company-phone', '+91 8080808080');
    await page.selectOption('#company-currency', 'INR');
    await page.fill('#company-email', 'e2e@testcompany.com');
    await page.fill('#company-website', 'https://testcompany.com');

    await page.click('button:has-text("Save company details")');
    await expectSuccess(
      page,
      'Company profile saved',
    );
  });

  // Bank details left the company profile in the cash-bank refactor: they are
  // now a first-class account register at /cash-bank/accounts, and the company
  // page only signposts it. The walk from one to the other is the part worth
  // covering — without the bank fills the rest of this test would be a copy of
  // 'saves company profile' above.
  test('adds a bank account from the company profile', async ({
    authedPage: page,
  }) => {
    await page.goto('/settings/company');
    await expect(page.locator('#company-name')).toBeVisible({ timeout: 5_000 });

    await page.fill('#company-name', 'Bank Details Corp');
    await page.fill('#company-address', '100 Finance Rd, Mumbai');
    await page.fill('#company-gst', uniqueGstin());
    await page.fill('#company-phone', '+91 7070707070');
    await page.click('button:has-text("Save company details")');
    await expectSuccess(page, 'Company profile saved');

    // Saved, so the link goes straight there without asking.
    await page.getByRole('link', { name: 'Cash & Bank Accounts →' }).click();
    await expect(page).toHaveURL('/cash-bank/accounts');
    await expect(page.locator('#new-account-display')).toBeVisible({ timeout: 5_000 });

    // 'bank' is the default type, but set it explicitly — the bank-only fields
    // below are conditional on it.
    await page.selectOption('#new-account-type', 'bank');
    const displayName = `ICICI ${Date.now().toString(36)}`;
    await page.fill('#new-account-display', displayName);
    await page.fill('#new-account-bank', 'ICICI Bank');
    await page.fill('#new-account-branch', 'Andheri East');
    await page.fill('#new-account-accno', '987654321098');
    await page.fill('#new-account-name', 'Bank Details Corp');
    await page.fill('#new-account-ifsc', 'ICIC0001234');
    await page.fill('#new-account-upi', 'bankdetailscorp@okicici');

    await page.click('button:has-text("Add account")');
    // This card reports inline rather than through the toast host, so
    // expectSuccess would never match here.
    await expect(
      page.locator('.empty-state').filter({ hasText: 'Account added successfully.' }),
    ).toBeVisible({ timeout: 5_000 });

    // The UPI ID is what the pay-by-UPI QR on a shared invoice points at, so it has
    // to survive the round trip. Stored exactly as typed: UPI leaves resolving the
    // local part to each bank's own mapper, so unlike IFSC it must not be re-cased.
    //
    // The list is sorted by display name and the demo seed already owns an
    // account with its own UPI ID, so `.first()` is not necessarily the account
    // this test just created. Find it by its unique display name and read the
    // UPI input that shares its id suffix.
    await page.reload();
    const createdName = page.locator(
      `input[id^="account-display-"][value="${displayName}"]`,
    );
    await expect(createdName).toBeVisible({ timeout: 5_000 });
    const accountId = (await createdName.getAttribute('id'))!.replace('account-display-', '');
    await expect(page.locator(`#account-upi-${accountId}`)).toHaveValue(
      'bankdetailscorp@okicici',
      { timeout: 5_000 },
    );
  });

  // Asserts the toggle round-trips in BOTH directions rather than that it starts
  // off. Every spec in this suite shares one seeded company, so its current value
  // is whatever the last test left behind; the default belongs in a backend test
  // (tests/api/test_company_settings.py), which owns a fresh row.
  //
  // For the same reason this restores whatever it found at the end. Leaving the
  // setting off would silently disable pay-online QRs on the shared company for
  // everything that runs afterwards -- including a human opening the dev app.
  test('pay-online QR setting round-trips', async ({ authedPage: page }) => {
    await page.goto('/settings/company');
    await expect(page.locator('#company-name')).toBeVisible({ timeout: 5_000 });

    const initial = await page.locator('#company-show-pay-qr').isChecked();

    await page.fill('#company-name', 'Pay QR Corp');
    await page.fill('#company-address', '5 QR Street, Pune');
    await page.fill('#company-gst', uniqueGstin());

    const saveAndReload = async (enabled: boolean) => {
      await page.locator('#company-show-pay-qr').setChecked(enabled);
      await page.click('button:has-text("Save company details")');
      await expectSuccess(page, 'Company profile saved');
      await page.reload();
      const reloaded = page.locator('#company-show-pay-qr');
      await expect(reloaded).toBeVisible({ timeout: 5_000 });
      return reloaded;
    };

    await expect(await saveAndReload(true)).toBeChecked();
    await expect(await saveAndReload(false)).not.toBeChecked();

    if (initial) {
      await saveAndReload(true);
    }
  });

  // Same shape as the pay-online QR test above, for the same reasons: round-trip
  // both ways, then put back whatever was there.
  test('pay by UPI button setting round-trips', async ({ authedPage: page }) => {
    await page.goto('/settings/company');
    await expect(page.locator('#company-name')).toBeVisible({ timeout: 5_000 });

    const toggle = '#company-show-upi-pay-button';
    const initial = await page.locator(toggle).isChecked();

    await page.fill('#company-name', 'UPI Button Corp');
    await page.fill('#company-address', '6 UPI Street, Pune');
    await page.fill('#company-gst', uniqueGstin());

    const saveAndReload = async (enabled: boolean) => {
      await page.locator(toggle).setChecked(enabled);
      await page.click('button:has-text("Save company details")');
      await expectSuccess(page, 'Company profile saved');
      await page.reload();
      const reloaded = page.locator(toggle);
      await expect(reloaded).toBeVisible({ timeout: 5_000 });
      return reloaded;
    };

    await expect(await saveAndReload(true)).toBeChecked();
    await expect(await saveAndReload(false)).not.toBeChecked();

    if (initial) {
      await saveAndReload(true);
    }
  });

  test('persists company data across page reloads', async ({
    authedPage: page,
  }) => {
    await page.goto('/settings/company');
    await expect(page.locator('#company-name')).toBeVisible({ timeout: 5_000 });

    const companyName = `Persist Co ${Date.now().toString(36)}`;
    await page.fill('#company-name', companyName);
    await page.fill('#company-address', 'Persist Street');
    await page.fill('#company-gst', uniqueGstin());
    await page.fill('#company-phone', '+91 6060606060');
    await page.click('button:has-text("Save company details")');
    await expectSuccess(page, 'Company profile saved');

    // Reload and verify
    await page.reload();
    await expect(page.locator('#company-name')).toBeVisible({ timeout: 5_000 });
    await expect(page.locator('#company-name')).toHaveValue(companyName);
  });

  test('currency dropdown has multiple options', async ({
    authedPage: page,
  }) => {
    await page.goto('/settings/company');
    await expect(page.locator('#company-currency')).toBeVisible({
      timeout: 5_000,
    });

    const options = page.locator('#company-currency option');
    const count = await options.count();
    expect(count).toBeGreaterThanOrEqual(3);
  });
});
