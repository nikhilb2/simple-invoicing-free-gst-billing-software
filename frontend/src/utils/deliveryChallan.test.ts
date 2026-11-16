import { describe, expect, it } from 'vitest';
import type { DeliveryChallan } from '../types/api';
import {
  CHALLAN_PURPOSES,
  CHALLAN_PURPOSE_LABELS,
  CHALLAN_STATUS_FILTERS,
  DEFAULT_CHALLAN_PURPOSE,
  allowedChallanActions,
  buildChallanPayload,
  challanCancelledMessage,
  challanFormView,
  challanLineTaxable,
  challanPdfFileName,
  challanProducts,
  challanSavedMessage,
  challanStatusBadgeClass,
  challanToFormState,
  challanTotalValue,
  initialChallanForm,
  isValidChallanNumber,
  parseChallanRouteId,
  readChallanListState,
  showChallanPlaceOfSupply,
  showChallansEmptyState,
  termsToText,
  validateChallanForm,
  formatChallanAge,
} from './deliveryChallan';

describe('purposes', () => {
  it('lists the seven purposes in dropdown order with the default first', () => {
    expect(CHALLAN_PURPOSES.map((p) => p.value)).toEqual([
      'supply_on_approval', 'job_work', 'liquid_gas', 'skd_ckd_lots', 'exhibition', 'own_use', 'other',
    ]);
    expect(DEFAULT_CHALLAN_PURPOSE).toBe(CHALLAN_PURPOSES[0].value);
    expect(CHALLAN_PURPOSE_LABELS.liquid_gas).toBe('Supply of liquid gas (quantity not known)');
    expect(CHALLAN_PURPOSE_LABELS.own_use).toBe('For own use / branch transfer');
  });

  it('has a status filter per status', () => {
    expect(CHALLAN_STATUS_FILTERS.map((c) => c.value)).toEqual(['open', 'invoiced', 'cancelled']);
  });
});

describe('allowedChallanActions', () => {
  it('offers everything while open', () => {
    expect(allowedChallanActions({ status: 'open' })).toEqual(['convert', 'edit', 'eway', 'cancel']);
  });
  it('offers only the e-way bill once invoiced', () => {
    expect(allowedChallanActions({ status: 'invoiced' })).toEqual(['eway']);
  });
  it('offers nothing once cancelled', () => {
    expect(allowedChallanActions({ status: 'cancelled' })).toEqual([]);
  });
});

describe('challanStatusBadgeClass', () => {
  it('uses the shared chip colours', () => {
    expect(challanStatusBadgeClass('open')).toBe('status-chip');
    expect(challanStatusBadgeClass('invoiced')).toBe('status-chip status-chip--success');
    expect(challanStatusBadgeClass('cancelled')).toBe('status-chip status-chip--cancelled');
  });
});

describe('isValidChallanNumber', () => {
  it.each(['', 'DC-2026-001', 'A', 'DC/26/0001', '1234567890123456'])('accepts %j', (value) => {
    expect(isValidChallanNumber(value)).toBe(true);
  });
  it.each(['12345678901234567', '-DC', '/DC', 'DC 1', 'DC_1', 'DC.1', ' DC'])('rejects %j', (value) => {
    expect(isValidChallanNumber(value)).toBe(false);
  });
});

describe('small helpers', () => {
  it('names the PDF file with slashes replaced', () => {
    expect(challanPdfFileName('DC/26/001')).toBe('delivery_challan_DC_26_001.pdf');
  });
  it('shows the empty state only for a loaded, empty list', () => {
    expect(showChallansEmptyState({ isLoading: false, isError: false, rowCount: 0 })).toBe(true);
    expect(showChallansEmptyState({ isLoading: true, isError: false, rowCount: 0 })).toBe(false);
    expect(showChallansEmptyState({ isLoading: false, isError: true, rowCount: 0 })).toBe(false);
    expect(showChallansEmptyState({ isLoading: false, isError: false, rowCount: 2 })).toBe(false);
  });
  it('words the toasts', () => {
    expect(challanSavedMessage('DC-1', false)).toBe('Delivery challan DC-1 saved. Stock has been reduced.');
    expect(challanSavedMessage('DC-1', true)).toBe('Delivery challan DC-1 updated. Stock has been adjusted.');
    expect(challanCancelledMessage('DC-1')).toBe('Delivery challan DC-1 cancelled. Its goods are back in stock.');
  });
  it('joins the company terms in serial order', () => {
    expect(termsToText([
      { serial_number: 2, content: 'Second' },
      { serial_number: 1, content: 'First' },
    ])).toBe('1. First\n2. Second');
    expect(termsToText([])).toBe('');
  });
  it('leaves serial-numbered products off', () => {
    const list = [{ id: 1, track_serials: false }, { id: 2, track_serials: true }];
    expect(challanProducts(list).map((p) => p.id)).toEqual([1]);
  });
  it('reads router state defensively', () => {
    expect(readChallanListState(null)).toEqual({});
    expect(readChallanListState('x')).toEqual({});
    expect(readChallanListState({ success: 'ok', openId: 4 })).toEqual({ success: 'ok', openId: 4 });
    expect(readChallanListState({ success: 3, openId: '4' })).toEqual({ success: undefined, openId: undefined });
  });
});

describe('line values', () => {
  it('multiplies quantity by the typed rate, else the product price', () => {
    expect(challanLineTaxable({ quantity: '3', unitPrice: '10.5' }, { price: 99 })).toBe(31.5);
    expect(challanLineTaxable({ quantity: '3', unitPrice: '' }, { price: 4 })).toBe(12);
    expect(challanLineTaxable({ quantity: 'abc', unitPrice: '5' }, undefined)).toBe(0);
  });
  it('rounds a fractional quantity to the paisa', () => {
    expect(challanLineTaxable({ quantity: '0.333', unitPrice: '10' }, undefined)).toBe(3.33);
  });
  it('totals the lines', () => {
    const lines = [
      { id: 1, productId: '1', quantity: '2', unitPrice: '', description: '' },
      { id: 2, productId: '2', quantity: '1', unitPrice: '7.25', description: '' },
      { id: 3, productId: '', quantity: '5', unitPrice: '', description: '' },
    ];
    expect(challanTotalValue(lines, [{ id: 1, price: 10 }, { id: 2, price: 100 }])).toBe(27.25);
  });
});

describe('validateChallanForm', () => {
  const valid = () => ({
    ...initialChallanForm('2026-11-15'),
    ledgerId: '3',
    items: [{ id: 1, productId: '9', quantity: '2', unitPrice: '', description: '' }],
  });

  it('accepts a complete form', () => {
    expect(validateChallanForm(valid())).toBeNull();
  });
  it('wants a customer', () => {
    expect(validateChallanForm({ ...valid(), ledgerId: '' })).toMatch(/customer/);
  });
  it('rejects a number that breaks Rule 55', () => {
    expect(validateChallanForm({ ...valid(), challanNumber: 'DC 1' })).toMatch(/16 characters/);
  });
  it('wants an item, a product on every line and a positive quantity', () => {
    expect(validateChallanForm({ ...valid(), items: [{ id: 1, productId: '', quantity: '1', unitPrice: '', description: '' }] })).toMatch(/at least one item/);
    const two = [...valid().items, { id: 2, productId: '', quantity: '1', unitPrice: '', description: '' }];
    expect(validateChallanForm({ ...valid(), items: two })).toMatch(/every line/);
    expect(validateChallanForm({ ...valid(), items: [{ id: 1, productId: '9', quantity: '0', unitPrice: '', description: '' }] })).toMatch(/quantity/);
  });
  it('wants a new shipping address to be filled in', () => {
    const form = { ...valid(), shippingSameAsBilling: false, shippingSelection: '__new__' };
    expect(validateChallanForm(form)).toMatch(/shipping address/);
    expect(validateChallanForm({ ...form, newShippingAddress: 'Plot 4' })).toBeNull();
  });
});

describe('buildChallanPayload', () => {
  const form = () => ({
    ...initialChallanForm('2026-11-15', '1. Goods remain ours'),
    ledgerId: '3',
    purpose: 'job_work' as const,
    items: [{ id: 1, productId: '9', quantity: '2.5', unitPrice: '', description: ' batch A ' }],
  });

  it('sends a blank number as null so the series numbers it', () => {
    const payload = buildChallanPayload(form(), '27');
    expect(payload).toMatchObject({
      ledger_id: 3,
      challan_number: null,
      challan_date: '2026-11-15',
      purpose: 'job_work',
      place_of_supply: '27',
      shipping_address_same_as_billing: true,
      terms_text: '1. Goods remain ours',
    });
    expect(payload.items).toEqual([{ product_id: 9, quantity: 2.5, unit_price: null, description: 'batch A' }]);
  });
  it('sends no place of supply when the company has no GSTIN', () => {
    expect(buildChallanPayload(form(), '').place_of_supply).toBeNull();
  });
  it('sends cleared terms as an empty string so an edit can remove them', () => {
    expect(buildChallanPayload({ ...form(), termsText: '  ' }, '').terms_text).toBe('');
  });
  it('sends a saved shipping address by id', () => {
    const payload = buildChallanPayload({ ...form(), shippingSameAsBilling: false, shippingSelection: '12' }, '');
    expect(payload).toMatchObject({ shipping_address_same_as_billing: false, shipping_address_id: 12 });
    expect(payload.new_shipping_address).toBeUndefined();
  });
  it('sends a new shipping address with its label', () => {
    const payload = buildChallanPayload({
      ...form(), shippingSameAsBilling: false, shippingSelection: '__new__', newShippingLabel: 'Site', newShippingAddress: ' Plot 4 ',
    }, '');
    expect(payload.new_shipping_address).toEqual({ label: 'Site', address: 'Plot 4' });
  });
});

describe('challanToFormState', () => {
  const challan = {
    id: 5, challan_number: 'DC-2026-001', status: 'open', purpose: 'exhibition', purpose_label: 'Exhibition or fair',
    challan_date: '2026-11-10', ledger_id: 3, place_of_supply: '29', shipping_address: 'Plot 4',
    shipping_address_label: 'Site', shipping_address_id: 8, reference_notes: 'Fragile', terms_text: null,
    items: [
      { id: 1, product_id: 9, quantity: 2.5, unit_price: 10, description: null },
      { id: 2, product_id: 4, quantity: 1, unit_price: 3, description: 'x' },
    ],
  } as unknown as DeliveryChallan;

  it('turns a saved challan back into form state', () => {
    const state = challanToFormState(challan);
    expect(state).toMatchObject({
      ledgerId: '3', challanNumber: 'DC-2026-001', purpose: 'exhibition', placeOfSupply: '29',
      shippingSameAsBilling: false, shippingSelection: '8', referenceNotes: 'Fragile', termsText: '',
    });
    expect(state.items).toEqual([
      { id: 1, productId: '9', quantity: '2.5', unitPrice: '10', description: '' },
      { id: 2, productId: '4', quantity: '1', unitPrice: '3', description: 'x' },
    ]);
  });
  it('round-trips through the payload', () => {
    const payload = buildChallanPayload(challanToFormState(challan), '29');
    expect(payload.ledger_id).toBe(3);
    expect(payload.shipping_address_id).toBe(8);
    expect(payload.items.map((i) => i.quantity)).toEqual([2.5, 1]);
  });
});

describe('form page view', () => {
  it('reads the route id, and marks a malformed one as NaN', () => {
    expect(parseChallanRouteId(undefined)).toBeNull();
    expect(parseChallanRouteId('12')).toBe(12);
    expect(parseChallanRouteId('abc')).toBeNaN();
    expect(parseChallanRouteId('0')).toBeNaN();
    expect(parseChallanRouteId('1.5')).toBeNaN();
  });

  it('shows the new-challan form once the lists load', () => {
    expect(challanFormView({ editingId: null, loading: true, challanFailed: false })).toBe('loading');
    expect(challanFormView({ editingId: null, loading: false, challanFailed: false })).toBe('form');
  });

  it('never shows an empty form when the challan to edit fails to load', () => {
    expect(challanFormView({ editingId: 9999, loading: false, challanFailed: true })).toBe('load-failed');
    expect(challanFormView({ editingId: Number.NaN, loading: false, challanFailed: false })).toBe('load-failed');
  });

  it('shows the edit form only for a loaded open challan', () => {
    expect(challanFormView({ editingId: 4, loading: true, challanFailed: false })).toBe('loading');
    expect(challanFormView({ editingId: 4, loading: false, challanFailed: false })).toBe('loading');
    expect(challanFormView({ editingId: 4, loading: false, challanFailed: false, status: 'open' })).toBe('form');
    expect(challanFormView({ editingId: 4, loading: false, challanFailed: false, status: 'invoiced' })).toBe('not-editable');
    expect(challanFormView({ editingId: 4, loading: false, challanFailed: false, status: 'cancelled' })).toBe('not-editable');
  });

  it('shows place of supply only for a company with a GSTIN, as the invoice form does', () => {
    expect(showChallanPlaceOfSupply('27AAAAA0000A1Z5')).toBe(true);
    expect(showChallanPlaceOfSupply('  ')).toBe(false);
    expect(showChallanPlaceOfSupply('')).toBe(false);
    expect(showChallanPlaceOfSupply(null)).toBe(false);
    expect(showChallanPlaceOfSupply(undefined)).toBe(false);
  });
});

describe('formatChallanAge', () => {
  it('uses the singular for one day only', () => {
    expect(formatChallanAge(0)).toBe('0 days');
    expect(formatChallanAge(1)).toBe('1 day');
    expect(formatChallanAge(2)).toBe('2 days');
    expect(formatChallanAge(31)).toBe('31 days');
  });
});
