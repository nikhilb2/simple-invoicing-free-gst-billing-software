---
title: "Delivery challans"
description: "Make a GST delivery challan for goods you send before billing, see what it does to stock, and convert it into a tax invoice."
---

# Delivery challans

A **delivery challan** lists goods you are sending to someone. It meets GST Rule 55. It is not a bill: it records no payment, makes no ledger entry and creates no tax liability. Use it when you send goods without a tax invoice, such as goods on approval, job work or a stock transfer.

A challan **does** take the goods out of stock, because they have left your premises.

## Choose the purpose

Pick the reason for the movement. It prints on the challan and decides the sub-supply type on an e-way bill.

| Purpose | Use it for |
|---|---|
| **Supply on approval** | Goods the customer can try and then keep or return. This is the default. |
| **Job work** | Goods sent to someone to process for you. |
| **Supply of liquid gas (quantity not known)** | Liquid gas where the exact quantity is only known later. |
| **SKD/CKD or in lots** | Goods sent in parts or in several lots. |
| **Exhibition or fair** | Goods taken to a show. |
| **For own use / branch transfer** | Goods moved to your own site or branch. |
| **Other** | Anything else. |

## Create one

1. Go to **Sales → Delivery Challans** and click **New delivery challan**.
2. Choose the **Customer**, the **Purpose** and the **Place of supply**.
3. Leave the **Challan number** blank to use the next one in the series (`DC-…`). If you type one, keep it to 16 characters. It must be unique.
4. Add lines: product, quantity and rate. The GST rate comes from the product.
5. Add notes or terms if you need them, then click **Save challan**.

There are no discounts, round-off, TDS or payments on a challan. Tax is worked out for each line so the invoice and the e-way bill can use it, but the PDF does not print tax amounts.

Serial-numbered products cannot go on a delivery challan yet.

## What happens to stock

The goods you send are always the goods that have left your stock.

| What you do | Stock |
|---|---|
| Save a challan | The quantity comes out. |
| Edit an open challan | Stock moves by the difference. |
| Cancel an open challan | The full quantity goes back in. |
| Convert it and invoice **less** | The invoice does not take stock out again. The difference goes back in. |
| Convert it and invoice **more** | The extra comes out. |
| Add a product that was not on the challan | It comes out as it does on any invoice. |
| Cancel that invoice | The challan is open again, and its goods are out again. |

Products that do not track stock are left alone.

## Statuses

| Status | Meaning | Actions |
|---|---|---|
| **Open** | Goods are out, no invoice yet. The list shows its age in days. | Edit, Convert, Cancel, PDF, E-way bill |
| **Invoiced** | An invoice was made from it. | PDF |
| **Cancelled** | Withdrawn. It keeps its number. | PDF |

## Convert to an invoice

1. On the list, click **Convert**, or choose **Convert to invoice** in the preview menu.
2. The invoice form opens with the customer, lines and quantities filled in. You can change anything.
3. If an invoice quantity differs from the challan, a note says what will happen, for example: *challan 12, invoicing 9. 3 will be added back to stock. Make sure they're returned.* It is a reminder, and it does not stop you.
4. Click **Create invoice**.

The challan number and date are kept on the invoice and print on its PDF, and the challan and the invoice link to each other. One challan makes one invoice.

## Print it

Click a number to open the preview, then **Download** or **Print**. The PDF has the Rule 55 details, a signature block and a **Received by** block. You can print up to three copies, labelled **Original for consignee**, **Duplicate for transporter** and **Triplicate for consignor**.

## E-way bill

Open the preview and choose **E-Way Bill** in the menu. It works like the invoice version, with the document type set to Delivery Challan. The sub-supply type follows the purpose and cannot be changed. Purposes with no NIC code of their own, such as supply on approval, use **Others**.

## Limits

- No serial-numbered products.
- No partial invoicing: one challan becomes one invoice, and you cannot merge challans.
- No returns or job-work receipts.
- Challans are not in GSTR-1 Table 13 yet.
- No share link or email. Download or print instead.
