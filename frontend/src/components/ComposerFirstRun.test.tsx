import { renderToString } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import {
  BILL_TYPE_HINT,
  BillTypeRow,
  FIRST_ITEM_HINT,
  FirstCustomerBox,
  FirstItemButton,
  QuotationsFirstRunNote,
  VoucherTypeSelect,
} from './ComposerFirstRun';

const noop = () => undefined;

describe('BillTypeRow', () => {
  it('shows Bill type, Sales invoice and a Change button, and no dropdown', () => {
    const html = renderToString(<BillTypeRow onChange={noop} />);
    expect(html).toContain('Bill type');
    expect(html).toContain('Sales invoice');
    expect(html).toContain('>Change</button>');
    expect(html).toContain('link-button link-button--tap');
    expect(html).not.toContain('<select');
    expect(html.indexOf('Bill type')).toBeLessThan(html.indexOf('Sales invoice'));
  });
});

describe('VoucherTypeSelect', () => {
  const render = (afterChange: boolean) => renderToString(
    <VoucherTypeSelect afterChange={afterChange} value="sales" disabled={false} onChange={noop}>
      <option value="sales">Sales</option>
    </VoucherTypeSelect>,
  );

  it('after Change, is the dropdown with the hint under it', () => {
    const html = render(true);
    expect(html).toContain('id="invoice-voucher-type"');
    expect(html).toContain(BILL_TYPE_HINT);
    expect(html).toContain('>Bill type</label>');
    expect(html).not.toContain('Voucher type');
    expect(BILL_TYPE_HINT).toBe('Purchase: a bill you got from a supplier. Quotation and proforma: offers, not bills.');
    expect(html).toContain('aria-describedby="invoice-voucher-type-hint"');
    expect(html.indexOf('<select')).toBeLessThan(html.indexOf('field-hint'));
  });

  it('is today\'s dropdown, without the hint, otherwise', () => {
    const html = render(false);
    expect(html).toContain('Voucher type');
    expect(html).not.toContain('field-hint');
  });
});

describe('FirstItemButton', () => {
  it('is a full-width ghost button with the tour target and the hint', () => {
    const html = renderToString(<FirstItemButton id="invoice-product-1" onClick={noop} />);
    expect(html).toContain('class="button button--ghost first-item-button"');
    expect(html).toContain('data-tour="add-product"');
    expect(html).toContain('id="invoice-product-1"');
    expect(html).toContain('Add your first item');
    expect(html).toContain(FIRST_ITEM_HINT);
    expect(FIRST_ITEM_HINT).toBe('Name, price and GST %. It goes on this bill and is saved for next time.');
  });
});

describe('FirstCustomerBox', () => {
  it('covers only the customer, with no product button', () => {
    const html = renderToString(<FirstCustomerBox onAdd={noop} />);
    expect(html).toContain('data-testid="invoice-first-run"');
    expect(html).toContain('Add your first customer');
    expect(html).toContain('Only the name is needed. Phone, address and GSTIN can come later.');
    expect(html).toContain('data-tour="add-customer"');
    expect(html).toContain('Add a customer');
    expect(html).not.toContain('add-product');
    expect(html).not.toContain('Add a product');
  });
});

describe('QuotationsFirstRunNote', () => {
  it('says a quotation is an offer and links to a new invoice', () => {
    const html = renderToString(<MemoryRouter><QuotationsFirstRunNote /></MemoryRouter>);
    expect(html).toContain('marketplace-note marketplace-note--emphasis');
    expect(html).toContain('A quotation is an offer, not a bill.');
    expect(html).toContain('It doesn&#x27;t count in your sales or GST. To bill a customer now, make an invoice.');
    expect(html).toContain('href="/invoices"');
    expect(html).toContain('button button--ghost button--small');
    expect(html).toContain('New invoice');
  });
});
