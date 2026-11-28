import { renderToStaticMarkup } from 'react-dom/server';
import { beforeEach, describe, expect, test } from 'vitest';
import ProductFormModal from './ProductFormModal';
import { HSN_ERROR, errorAfterHsnEdit } from './productFormRules';
import type { CatalogueRow } from './types';

function row(overrides: Partial<CatalogueRow> = {}): CatalogueRow {
  return {
    id: 41,
    sku: 'TEE-RED-M',
    name: 'Cotton tee, red, M',
    description: 'Combed cotton',
    hsn_sac: '6109',
    purchase_price: 180,
    selling_price: 349,
    current_stock: 25,
    reorder_level: 5,
    status: 'active',
    unit: 'Pieces',
    gst_rate: 5,
    track_serials: false,
    maintain_inventory: true,
    allow_decimal: false,
    is_producable: false,
    production_cost: null,
    date_added: '2026-04-01',
    last_sold_at: null,
    ...overrides,
  };
}

const noop = () => {};

/* No DOM here, so storage is an in-memory stand-in holding the form's prefs. */
let store: Record<string, string> = {};
Object.defineProperty(globalThis, 'localStorage', {
  configurable: true,
  value: {
    getItem: (key: string) => (key in store ? store[key] : null),
    setItem: (key: string, value: string) => {
      store[key] = String(value);
    },
    removeItem: (key: string) => {
      delete store[key];
    },
    clear: () => {
      store = {};
    },
  },
});

function storePrefs(prefs: object) {
  localStorage.setItem('product_form_prefs', JSON.stringify(prefs));
}

/* Vitest runs in node with no DOM here, so the form is read back from the
   server-rendered markup. */
function render(props: { row?: CatalogueRow | null; template?: CatalogueRow | null; countsStock?: boolean }) {
  const html = renderToStaticMarkup(
    <ProductFormModal
      row={props.row ?? null}
      template={props.template}
      countsStock={props.countsStock}
      onCancel={noop}
      onSaved={noop}
      onNeedsSerialBackfill={noop}
      onConfigureBom={noop}
    />,
  );
  const value = (id: string) => html.match(new RegExp(`<input id="${id}"[^>]*value="([^"]*)"`))?.[1];
  // In render order: maintain stock, fractional quantities, serials, manufactured in-house.
  const checkboxes = [...html.matchAll(/<input type="checkbox"[^>]*>/g)].map((m) => m[0].includes('checked=""'));
  return { html, value, checkboxes };
}

describe('ProductFormModal duplicate', () => {
  // These read every field, so "More options" is left open as a user would.
  beforeEach(() => {
    localStorage.clear();
    storePrefs({ showAdvanced: true, used: [] });
  });

  test('opens as a new product prefilled with the attributes similar products share', () => {
    const { html, value, checkboxes } = render({ template: row() });

    expect(html).toContain('New product from Cotton tee, red, M');
    expect(html).toContain('Create product');
    expect(value('product-name')).toBe('Cotton tee, red, M');
    expect(value('product-price')).toBe('349');
    expect(value('product-purchase-price')).toBe('180');
    expect(html).toMatch(/<option value="5" selected="">/);
    expect(value('product-hsn')).toBe('6109');
    expect(value('product-reorder')).toBe('5');
    expect(html).toMatch(/<textarea id="product-description"[^>]*>Combed cotton<\/textarea>/);
    expect(checkboxes).toEqual([true, false, false, false]);
  });

  test('leaves the SKU blank and starts with no opening stock', () => {
    const { html, value } = render({ template: row({ current_stock: 25 }) });

    expect(value('product-sku')).toBe('');
    expect(html).toContain('Opening stock');
    expect(value('product-initial-qty')).toBe('0');
  });

  test('copies the unit and the behaviour flags', () => {
    const { value, checkboxes } = render({
      template: row({ unit: 'Box of 12', maintain_inventory: false, allow_decimal: true }),
    });

    expect(value('product-custom-unit')).toBe('Box of 12');
    expect(checkboxes).toEqual([false, true, false, false]);
  });

  test('keeps serial tracking on, but carries none of the source serials', () => {
    const { html, checkboxes } = render({ template: row({ track_serials: true, current_stock: 3 }) });

    expect(checkboxes[2]).toBe(true);
    expect(html).toContain('Serials (0)');
    expect(html).not.toContain('class="serial-chip"');
  });

  test('keeps a producable product producable, with its production cost', () => {
    const { value, checkboxes } = render({ template: row({ is_producable: true, production_cost: 120.5 }) });

    expect(checkboxes[3]).toBe(true);
    expect(value('product-production-cost')).toBe('120.5');
  });

  test('editing and plain create are unchanged', () => {
    const edit = render({ row: row() });
    expect(edit.html).toContain('Editing Cotton tee, red, M');
    expect(edit.value('product-sku')).toBe('TEE-RED-M');

    const create = render({});
    expect(create.html).toContain('Add a product');
    expect(create.value('product-name')).toBe('');
  });

  test('the SKU is optional and comes after the product name', () => {
    const { html } = render({});

    expect(html).toContain('Item code (SKU) (optional)');
    expect(html).toContain('make one from the name');
    expect(html).not.toMatch(/<input[^>]*id="product-sku"[^>]*required/);
    expect(html.indexOf('id="product-name"')).toBeLessThan(html.indexOf('id="product-sku"'));
  });

  test('a new product starts with no GST rate chosen, and a 0% choice shows a note', () => {
    const create = render({});
    expect(create.html).toMatch(/<option value="" disabled="" selected="">Choose a rate<\/option>/);
    expect(create.html).not.toContain('You are charging no GST');
    expect(create.html).toContain('Item code (SKU)');
    expect(create.html).toContain('class="required-mark"');

    const zero = render({ row: row({ gst_rate: 0 }) });
    expect(zero.html).toContain('You are charging no GST on this product');
  });

  test('an unusual existing rate opens under Other rate with its own value', () => {
    const odd = render({ row: row({ gst_rate: 0.25 }) });
    expect(odd.html).toMatch(/<option value="__other__" selected="">/);
    expect(odd.value('product-gst-other')).toBe('0.25');
  });

  test('warns that a new tracked product with no opening stock cannot be sold yet', () => {
    const create = render({});
    expect(create.html).toContain('data-testid="product-no-stock-warning"');
    expect(create.html).toContain('Stop tracking stock for this item');

    // Editing never shows opening stock, and an untracked product has nothing to warn about.
    expect(render({ row: row() }).html).not.toContain('product-no-stock-warning');
    expect(render({ template: row({ maintain_inventory: false }) }).html).not.toContain('product-no-stock-warning');
  });
});

describe('editing the HSN code', () => {
  test('withdraws the HSN complaint once the field changes', () => {
    expect(errorAfterHsnEdit(HSN_ERROR)).toBe('');
  });

  test('leaves any other error on screen', () => {
    expect(errorAfterHsnEdit('Choose a GST rate.')).toBe('Choose a GST rate.');
    expect(errorAfterHsnEdit('')).toBe('');
  });
});

describe('ProductFormModal more options', () => {
  beforeEach(() => localStorage.clear());

  test('a first product shows only the basics, with the rest behind More options', () => {
    const { html, value } = render({});

    for (const id of ['product-name', 'product-sku', 'product-price', 'product-hsn', 'product-initial-qty']) {
      expect(value(id), id).toBeDefined();
    }
    expect(html).toContain('id="product-gst"');
    expect(html).toContain('More options');
    expect(html).toContain('purchase price, reorder level, description, stock counting');
    expect(html).not.toContain('id="product-purchase-price"');
    expect(html).not.toContain('id="product-reorder"');
    expect(html).not.toContain('id="product-description"');
    expect(html).not.toContain('How this product is tracked');
    expect(html).not.toMatch(/<input id="product-more-options"[^>]*checked/);
  });

  test('left open last time, every option shows', () => {
    storePrefs({ showAdvanced: true, used: [] });
    const { html } = render({});

    expect(html).toMatch(/<input id="product-more-options"[^>]*checked/);
    expect(html).toContain('id="product-purchase-price"');
    expect(html).toContain('Track individual serial numbers');
  });

  test('options used on the last product show even while closed', () => {
    storePrefs({ showAdvanced: false, used: ['purchase_price', 'track_serials'] });
    const { html } = render({});

    expect(html).toContain('id="product-purchase-price"');
    expect(html).toContain('Track individual serial numbers');
    expect(html).not.toContain('id="product-reorder"');
    expect(html).not.toContain('manufactured in-house');
    expect(html).toContain('reorder level, description, stock counting, fractional quantities, manufacturing');
  });

  test('editing never hides a setting the product has', () => {
    const { html, value } = render({ row: row({ track_serials: true, description: '', reorder_level: 0 }) });

    expect(value('product-purchase-price')).toBe('180');
    expect(html).toContain('Track individual serial numbers');
    expect(html).not.toContain('id="product-reorder"');
    expect(html).not.toContain('id="product-description"');
  });
});

describe('ProductFormModal stock counting (issue 983)', () => {
  beforeEach(() => localStorage.clear());

  test('a company that counts no stock yet gets a product it can bill straight away', () => {
    const { html, value } = render({ countsStock: false });

    // No opening quantity to answer and no "you cannot sell it" warning.
    expect(value('product-initial-qty')).toBeUndefined();
    expect(html).not.toContain('product-no-stock-warning');
    expect(html).toContain('data-testid="product-stock-not-counted"');
    expect(html).toContain('Count stock for this item');
    // The stock box is on screen, unticked, even with More options closed.
    expect(html).toMatch(/<input type="checkbox"(?![^>]*checked)[^>]*><span>Keep count of stock for this product/);
  });

  test('a company that counts stock keeps the old default: counted, with opening stock asked', () => {
    for (const countsStock of [true, undefined]) {
      const { html, value } = render({ countsStock });
      expect(value('product-initial-qty')).toBe('0');
      expect(html).toContain('data-testid="product-no-stock-warning"');
      expect(html).not.toContain('product-stock-not-counted');
    }
  });

  test('a duplicate follows its source product, not the company default', () => {
    const { value } = render({ template: row({ maintain_inventory: true }), countsStock: false });
    expect(value('product-initial-qty')).toBe('0');
  });
});

describe('ProductFormModal field errors (issue 1153)', () => {
  test('turns the browser bubble off so our own messages run, in create and in edit', () => {
    expect(render({}).html).toMatch(/<form[^>]*novalidate=""/);
    expect(render({ row: row() }).html).toMatch(/<form[^>]*novalidate=""/);
  });

  test('shows no field message before a save was tapped', () => {
    expect(render({}).html).not.toContain('field-error');
  });
});
