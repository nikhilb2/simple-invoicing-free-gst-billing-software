import { describe, expect, test } from 'vitest';
import { composerNextStep, forPointer, guideFor, mayNeedFirstInvoiceHelp, pickTarget, showComposerNextStep, tourOffer, type ComposerFacts, type FieldState, type Guide } from './tourSteps';

const EMPTY: ComposerFacts = {
  ledgerCount: 0,
  productCount: 0,
  ledgerChosen: false,
  productChosen: false,
  isSales: true,
  stockShortage: false,
  ledgerFormOpen: false,
  productFormOpen: false,
  stockFormOpen: false,
};
const READY: ComposerFacts = { ...EMPTY, ledgerCount: 1, productCount: 1, ledgerChosen: true, productChosen: true };

const id = (facts: Partial<ComposerFacts>, base = EMPTY) => guideFor({ ...base, ...facts }).id;

describe('guideFor follows what exists, not a saved position', () => {
  test('before the page has loaded', () => {
    expect(guideFor(null).id).toBe('loading');
  });

  test('walks customer, product, choosing, then creating', () => {
    expect(id({})).toBe('customer');
    expect(id({ ledgerCount: 1 })).toBe('product');
    expect(id({ ledgerCount: 1, productCount: 1 })).toBe('pick-customer');
    expect(id({ ledgerCount: 1, productCount: 1, ledgerChosen: true })).toBe('pick-product');
    expect(id({}, READY)).toBe('create');
  });

  test('skips what the company already has', () => {
    expect(id({ ledgerCount: 3, productCount: 2, ledgerChosen: true })).toBe('pick-product');
  });

  test('an open form comes first', () => {
    expect(id({ ledgerFormOpen: true })).toBe('customer-form');
    expect(id({ productFormOpen: true })).toBe('product-form');
    expect(id({ stockFormOpen: true }, READY)).toBe('stock-form');
  });

  test('a stock shortage is dealt with before anything else on the page', () => {
    expect(id({ stockShortage: true }, READY)).toBe('stock-shortage');
    expect(id({ stockShortage: true, stockFormOpen: true }, READY)).toBe('stock-form');
  });

  test('another voucher type is brought back to sales', () => {
    expect(id({ isSales: false }, READY)).toBe('voucher');
  });
});

describe('the steps', () => {
  const READ_ALL: FieldState = { visible: true, value: '', focused: false };
  const fieldTitles = (guide: Guide, hidden: string[] = []) => {
    const titles: string[] = [];
    const filled = new Set<string>();
    // Walk the form the way a person does: fill each field in turn, then leave it.
    for (let guard = 0; guard < 10; guard += 1) {
      const target = pickTarget(guide, (selector) => ({
        ...READ_ALL,
        visible: !hidden.includes(selector),
        value: filled.has(selector) ? '5' : '',
      }));
      if (!target) break;
      titles.push(target.title);
      if (target === guide.action) break;
      filled.add(target.selector);
    }
    return titles;
  };
  const all = () => {
    const ids = [
      { ...EMPTY },
      { ...EMPTY, ledgerCount: 1 },
      { ...EMPTY, ledgerFormOpen: true },
      { ...EMPTY, productFormOpen: true },
      { ...EMPTY, isSales: false },
      { ...READY, stockShortage: true },
      { ...READY, stockFormOpen: true },
      { ...READY, productChosen: false },
      { ...READY, ledgerChosen: false },
      READY,
    ];
    return ids.map((facts) => guideFor(facts));
  };

  test('customer: Name, then Save', () => {
    const guide = guideFor({ ...EMPTY, ledgerFormOpen: true });
    expect(fieldTitles(guide)).toEqual(['Customer name', 'Save the customer']);
  });

  test('product: Name, Price, GST %, Opening stock only when it is on screen, then Save', () => {
    const guide = guideFor({ ...EMPTY, productFormOpen: true });
    expect(fieldTitles(guide)).toEqual(['Product name', 'Price', 'GST %', 'Stock you have now', 'Save the product']);
    expect(fieldTitles(guide, ['#modal-product-opening-stock'])).toEqual(['Product name', 'Price', 'GST %', 'Save the product']);
  });

  test('GST % says to choose the rate, and Save the customer says Tap Save', () => {
    const gst = guideFor({ ...EMPTY, productFormOpen: true }).fields?.find((f) => f.title === 'GST %');
    expect(gst?.body).toBe('Choose the rate. It prints on the bill and in your GST return.');
    const save = guideFor({ ...EMPTY, ledgerFormOpen: true }).action;
    expect(forPointer(save?.body ?? '', true)).toBe('Tap Save. You can add phone and address later.');
    expect(forPointer(save?.body ?? '', false)).toBe('Click Save. You can add phone and address later.');
  });

  test('no steps for phone, address or SKU', () => {
    const selectors = all().flatMap((guide) => (guide.fields ?? []).map((field) => field.selector));
    expect(selectors.join(' ')).not.toMatch(/phone|address|sku/);
  });

  test('plain words: no ledger, SKU or opening balance', () => {
    for (const guide of all()) {
      for (const text of [guide.title, guide.body, ...(guide.fields ?? []).flatMap((f) => [f.title, f.body]), guide.action?.title ?? '', guide.action?.body ?? '']) {
        expect(text).not.toMatch(/ledger|SKU|opening balance/i);
      }
    }
  });

  test('uses the agreed words for the step texts', () => {
    expect(guideFor(EMPTY).action?.body).toBe('Tap Add a customer. You stay on this page.');
    expect(guideFor({ ...EMPTY, ledgerFormOpen: true }).action?.body).toBe('Tap Save. You can add phone and address later.');
    expect(guideFor({ ...READY, stockShortage: true }).action?.body).toBe('Not enough in stock for this bill. Tap here to add it. Your bill stays as it is.');
    expect(guideFor(READY).action?.body).toBe('Tap Create invoice. This saves a real bill.');
  });

  test('"Tap" on a touch screen, "Click" with a mouse', () => {
    expect(forPointer('Tap Save.', true)).toBe('Tap Save.');
    expect(forPointer('Tap Save.', false)).toBe('Click Save.');
    for (const guide of all()) {
      const texts = [guide.body, guide.action?.body ?? '', ...(guide.fields ?? []).map((f) => f.body)];
      for (const text of texts) expect(forPointer(text, true)).not.toMatch(/\bClick\b/);
    }
  });
});

describe('pickTarget', () => {
  const guide: Guide = {
    id: 'form',
    step: 1,
    title: '',
    body: '',
    fields: [
      { selector: '#name', title: 'name', body: '' },
      { selector: '#stock', title: 'stock', body: '', positive: true },
    ],
    action: { selector: '#save', title: 'save', body: '' },
  };
  const blank: FieldState = { visible: true, value: '', focused: false };
  const read = (fields: Record<string, Partial<FieldState>>) => (selector: string): FieldState => ({
    ...blank,
    ...fields[selector],
  });

  test('starts at the first empty field', () => {
    expect(pickTarget(guide, read({}))?.title).toBe('name');
  });

  test('stays on a field while it is being typed in', () => {
    expect(pickTarget(guide, read({ '#name': { value: 'A', focused: true } }))?.title).toBe('name');
  });

  test('moves on once the field is filled and left', () => {
    expect(pickTarget(guide, read({ '#name': { value: 'Asha' } }))?.title).toBe('stock');
  });

  test('zero does not count for a field that needs a positive number', () => {
    expect(pickTarget(guide, read({ '#name': { value: 'Asha' }, '#stock': { value: '0' } }))?.title).toBe('stock');
    expect(pickTarget(guide, read({ '#name': { value: 'Asha' }, '#stock': { value: '5' } }))?.title).toBe('save');
  });

  test('a field that is not on screen is passed over', () => {
    expect(
      pickTarget(guide, read({ '#name': { value: 'Asha' }, '#stock': { visible: false } }))?.title,
    ).toBe('save');
  });

  test('nothing to point at when the action is not on screen either', () => {
    const hidden = { visible: false };
    expect(pickTarget(guide, read({ '#name': hidden, '#stock': hidden, '#save': hidden }))).toBeNull();
  });
});

describe('tourOffer', () => {
  const none = { sales: { sales_invoice_count: 0, purchase_invoice_count: 0 } } as Parameters<typeof tourOffer>[2];
  const some = { sales: { sales_invoice_count: 2, purchase_invoice_count: 0 } } as Parameters<typeof tourOffer>[2];

  test('offered to an owner of a company with no invoices', () => {
    expect(tourOffer(null, 'admin', none)).toBe('offer');
    expect(tourOffer(null, 'manager', none)).toBe('offer');
  });

  test.each(['completed', 'skipped', 'not_needed'] as const)('never again after %s', (status) => {
    expect(tourOffer(status, 'admin', none)).toBe('none');
  });

  test('marked not needed once the company has invoices, whatever the role', () => {
    expect(tourOffer(null, 'admin', some)).toBe('not_needed');
    expect(tourOffer(null, 'staff', some)).toBe('not_needed');
  });

  test('not offered to staff, and nothing is saved for them', () => {
    expect(tourOffer(null, 'staff', none)).toBe('none');
  });

  test('decides nothing until the account and figures have loaded', () => {
    expect(tourOffer(undefined, 'admin', none)).toBe('none');
    expect(tourOffer(null, 'admin', null)).toBe('none');
  });
});

describe('after "Exit walkthrough": the next step on the composer', () => {
  test('follows the form: customer, then the first item, then the total', () => {
    expect(composerNextStep({ ledgerChosen: false, productChosen: false })).toBe('Next: pick your customer or add a new one.');
    expect(composerNextStep({ ledgerChosen: true, productChosen: false })).toBe('Next: add the first item.');
    expect(composerNextStep({ ledgerChosen: true, productChosen: true })).toBe('Next: check the total, then tap Create invoice.');
  });

  test('goes back a step when the customer or the item is cleared', () => {
    expect(composerNextStep({ ledgerChosen: false, productChosen: true })).toBe('Next: pick your customer or add a new one.');
  });

  test('only looks for an invoice while the walkthrough is unanswered or skipped', () => {
    expect(mayNeedFirstInvoiceHelp(null)).toBe(true);
    expect(mayNeedFirstInvoiceHelp('skipped')).toBe(true);
    expect(mayNeedFirstInvoiceHelp('completed')).toBe(false);
    expect(mayNeedFirstInvoiceHelp('not_needed')).toBe(false);
    expect(mayNeedFirstInvoiceHelp(undefined)).toBe(false);
  });

  test('shows on a new sales invoice while the company has no invoice and the walkthrough is not running', () => {
    expect(showComposerNextStep({ tourRunning: false, hasInvoice: false, isNewSalesInvoice: true })).toBe(true);
  });

  test('hides while the walkthrough runs, so "Show me how" restarts it rather than doubling it', () => {
    expect(showComposerNextStep({ tourRunning: true, hasInvoice: false, isNewSalesInvoice: true })).toBe(false);
  });

  test('hides once there is an invoice, or before that is known', () => {
    expect(showComposerNextStep({ tourRunning: false, hasInvoice: true, isNewSalesInvoice: true })).toBe(false);
    expect(showComposerNextStep({ tourRunning: false, hasInvoice: null, isNewSalesInvoice: true })).toBe(false);
  });

  test('hides on a purchase, a quotation or an edit', () => {
    expect(showComposerNextStep({ tourRunning: false, hasInvoice: false, isNewSalesInvoice: false })).toBe(false);
  });

  test('the dashboard offer still stays answered after a skip; restarting does not depend on it', () => {
    const none = { sales: { sales_invoice_count: 0, purchase_invoice_count: 0 } } as Parameters<typeof tourOffer>[2];
    expect(tourOffer('skipped', 'admin', none)).toBe('none');
    expect(showComposerNextStep({ tourRunning: false, hasInvoice: false, isNewSalesInvoice: true })).toBe(true);
  });
});
