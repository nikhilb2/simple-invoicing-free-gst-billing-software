---
title: "Quick start: create your first GST invoice"
description: "Set up Simple Invoicing, the free GST billing software, and send your first GST invoice in about ten minutes: account, company, customer, product, invoice."
---

# Quick start

This page takes you from a new account to your first invoice. It takes about ten minutes.

Simple Invoicing runs in your browser on a laptop or phone, with nothing to install. These steps use the hosted version at [app.gstbill.in](https://app.gstbill.in). If you [run your own copy](../integrations/self-hosting), start at step 2.

## 1. Create your account

1. Open the [sign-up page](https://app.gstbill.in/register).
2. Enter your **Full name** and **Email**, then click **Create account**. Or click **Sign up with Google** and skip to step 2.
3. Open the link we email you. It is valid for 24 hours.
4. Check **Your name**, which is filled in from sign-up, and choose a **Password** of at least 8 characters. Common passwords are refused. Click **Confirm email and set password**.
5. If you opened the link in the browser you signed up with, within 10 minutes, you are signed in straight away. Otherwise click **Continue to sign in**.

![The sign-up page](/screens/register.webp)

If no email arrives, check your spam folder. The **Resend verification email** button sends another link. If you already have an account with this address, the email tells you how to sign in instead, with **Continue with Google** if that is how you signed up.

## 2. Set up your company

The first time you sign in, the app asks for your company details. Enter at least the **Company name** and **Address**, and your **GSTIN** if you have one. **Currency** starts on **INR - Indian Rupee**.

Click **Save company details**. A box then offers **Create my first invoice**, which starts the walkthrough described below. Or choose **Skip for now** to go to the dashboard. [Company setup](./company-setup) covers every other option, including invoice numbering, your logo, bank details and terms.

The dashboard then shows a **Get started** checklist with the next steps below. It goes away once you have created an invoice, or you can hide it.

The dashboard also offers to walk you through your first invoice. Click **Show me how** and the app points at each field while you add a real customer and product and create the invoice. If you choose **Skip for now**, you can start it later with **Walk me through it** on the checklist. Admins and managers see this.

## 3. Add a customer

1. Click **Ledgers** in the sidebar, then **Create ledger**.
2. Enter the **Ledger name**. **Phone number**, **Address** and the customer's **GSTIN** are optional; fill them in if you have them.
3. Click **Create ledger**.

The GSTIN decides how tax is split, so enter it carefully. See [Ledgers](../ledgers/).

## 4. Add a product

1. Go to **Catalogue → Products & Stock** and click **New product**.
2. Enter the **Product name**, **Selling price**, **GST rate** and **HSN / SAC**. The **SKU** is optional. Leave it blank and one is made from the name.
3. Enter how many you have now. For a service, untick **Maintain stock for this product**.
4. Click **Create product**.

See [Products and stock](../catalogue/products).

## 5. Create your first invoice

1. Go to **Sales → Invoices**.
2. Check that **Voucher type** says Sales, then choose your customer under **Ledger**. The place of supply fills in from their GSTIN.
3. Choose your product on the first line and enter the quantity. GST is worked out as you go.
4. Click **Create invoice**.

Stock falls and the amount appears on the customer's ledger straight away. See [Invoices](../sales/invoices).

## 6. Send it and get paid

From the invoice preview, download the PDF, email it, or share a link on WhatsApp. See [Send and share](../sales/sending).

When the money arrives, click **Record payment** on the invoice. See [Cash and bank](../sales/cash-bank).

## What to read next

- [Finding your way around](./tour): the sidebar, the company switcher and keyboard shortcuts.
- [GSTR-1 filing](../reports/gstr1): export your return at month-end.
- [Connect an AI assistant](../integrations/ai-assistants): ask Claude or ChatGPT about your books.
