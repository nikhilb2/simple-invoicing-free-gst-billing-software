import type { DashboardMetrics, UserProfile } from '../../types/api';
import { hasPostedInvoices } from '../../utils/getStarted';

export type FirstInvoiceTourStatus = 'completed' | 'skipped' | 'not_needed';

/** What the invoice page knows right now. The walkthrough follows this, so it never asks for something already done. */
export type ComposerFacts = {
  ledgerCount: number;
  productCount: number;
  ledgerChosen: boolean;
  productChosen: boolean;
  isSales: boolean;
  stockShortage: boolean;
  ledgerFormOpen: boolean;
  productFormOpen: boolean;
  stockFormOpen: boolean;
};

export type GuideTarget = {
  selector: string;
  title: string;
  body: string;
  /** A field that is only done once it holds a number above zero, such as opening stock. */
  positive?: boolean;
};

export type Guide = {
  id: string;
  /** 1 to TOUR_STEPS, for the progress marker. */
  step: number;
  title: string;
  body: string;
  /** Form fields, in order. The first unfinished one is highlighted. */
  fields?: GuideTarget[];
  /** Highlighted when no field is left to fill in. */
  action?: GuideTarget;
};

export const TOUR_STEPS = 4;
export const INVOICE_PATH = '/invoices';

const tour = (name: string) => `[data-tour="${name}"]`;

const CUSTOMER: Guide = {
  id: 'customer',
  step: 1,
  title: 'Add your customer',
  body: 'Everything you create here is real, so use a real customer if you can.',
  action: {
    selector: tour('add-customer'),
    title: 'Add your customer',
    body: 'Tap Add a customer. You stay on this page.',
  },
};

const CUSTOMER_FORM: Guide = {
  id: 'customer-form',
  step: 1,
  title: 'Fill in the customer',
  body: 'Only the name is needed.',
  fields: [
    {
      selector: '#modal-ledger-name',
      title: 'Customer name',
      body: 'As it should print on the bill.',
    },
  ],
  action: {
    selector: tour('save-customer'),
    title: 'Save the customer',
    body: 'Tap Save. You can add phone and address later.',
  },
};

const PRODUCT: Guide = {
  id: 'product',
  step: 2,
  title: 'Add what you sold',
  body: 'Add the product or service that goes on this bill.',
  action: {
    selector: tour('add-product'),
    title: 'Add what you sold',
    body: 'Tap Add your first item.',
  },
};

const PRODUCT_FORM: Guide = {
  id: 'product-form',
  step: 2,
  title: 'Fill in the product',
  body: 'Only a few fields are needed for now.',
  fields: [
    {
      selector: '#modal-product-name',
      title: 'Product name',
      body: 'As it should print on the bill.',
    },
    {
      selector: '#modal-product-price',
      title: 'Price',
      body: 'What you charge for one.',
    },
    {
      selector: '#modal-product-gst-rate',
      title: 'GST %',
      body: 'Choose the rate. It prints on the bill and in your GST return.',
    },
    {
      // Only on screen while Maintain inventory is ticked; pickTarget passes over a field that is not.
      selector: '#modal-product-opening-stock',
      title: 'Stock you have now',
      body: 'How many you have today.',
      positive: true,
    },
  ],
  action: {
    selector: tour('save-product'),
    title: 'Save the product',
    body: 'Tap Save. You can add the rest later.',
  },
};

const VOUCHER: Guide = {
  id: 'voucher',
  step: 3,
  title: 'Switch back to Sales',
  body: 'This guide makes a sales bill.',
  action: {
    selector: '#invoice-voucher-type',
    title: 'Switch back to Sales',
    body: 'This guide makes a sales bill. Choose Sales here.',
  },
};

const PICK_CUSTOMER: Guide = {
  id: 'pick-customer',
  step: 3,
  title: 'Pick the customer',
  body: 'Choose who this bill is for.',
  action: {
    selector: '#invoice-ledger',
    title: 'Pick the customer',
    body: 'Tap here and choose who this bill is for.',
  },
};

const PICK_PRODUCT: Guide = {
  id: 'pick-product',
  step: 3,
  title: 'Pick what you sold',
  body: 'Choose the item for the first line of the bill.',
  action: {
    selector: 'input[id^="invoice-product-"]',
    title: 'Pick what you sold',
    body: 'Tap here and choose the item. Then check the quantity and price.',
  },
};

const STOCK_SHORTAGE: Guide = {
  id: 'stock-shortage',
  step: 4,
  title: 'Add the missing stock',
  body: 'There is not enough of this item in stock for this bill.',
  action: {
    selector: tour('add-stock'),
    title: 'Add the missing stock',
    body: 'Not enough in stock for this bill. Tap here to add it. Your bill stays as it is.',
  },
};

const STOCK_FORM: Guide = {
  id: 'stock-form',
  step: 4,
  title: 'Save the stock',
  body: 'Check the quantity, then save.',
  action: {
    selector: tour('save-stock'),
    title: 'Save the stock',
    body: 'The missing quantity is filled in. Tap Save.',
  },
};

const CREATE: Guide = {
  id: 'create',
  step: 4,
  title: 'Create the invoice',
  body: 'Check the details, then create the invoice.',
  action: {
    selector: tour('create-invoice'),
    title: 'Create the invoice',
    body: 'Tap Create invoice. This saves a real bill.',
  },
};

/** The steps are written for a touch screen ("Tap"); a mouse says "Click". */
export function forPointer(text: string, coarsePointer: boolean): string {
  return coarsePointer ? text : text.replace(/\bTap\b/g, 'Click');
}

export const LOADING_GUIDE: Guide = {
  id: 'loading',
  step: 1,
  title: 'Opening the invoice page',
  body: 'Just a moment.',
};

export const AWAY_GUIDE: Guide = {
  id: 'away',
  step: 1,
  title: 'Your invoice is waiting',
  body: 'You left the invoice page. Go back to carry on from where you stopped.',
};

/** The next thing to do, worked out from what exists rather than from a saved position. */
export function guideFor(facts: ComposerFacts | null): Guide {
  if (!facts) return LOADING_GUIDE;
  if (facts.ledgerFormOpen) return CUSTOMER_FORM;
  if (facts.productFormOpen) return PRODUCT_FORM;
  if (facts.stockFormOpen) return STOCK_FORM;
  if (!facts.isSales) return VOUCHER;
  if (facts.ledgerCount === 0) return CUSTOMER;
  if (facts.productCount === 0) return PRODUCT;
  if (facts.stockShortage) return STOCK_SHORTAGE;
  if (!facts.ledgerChosen) return PICK_CUSTOMER;
  if (!facts.productChosen) return PICK_PRODUCT;
  return CREATE;
}

export type FieldState = {
  /** The element exists and takes up space on screen. */
  visible: boolean;
  value: string;
  focused: boolean;
};

function fieldIsFinished(field: GuideTarget, state: FieldState): boolean {
  // Still being typed in: moving on now would pull the hint away mid-word.
  if (state.focused) return false;
  const value = state.value.trim();
  return field.positive ? Number(value) > 0 : value !== '';
}

/** Which part of the guide to point at: the first unfinished field, then the action. */
export function pickTarget(guide: Guide, readField: (selector: string) => FieldState): GuideTarget | null {
  for (const field of guide.fields ?? []) {
    const state = readField(field.selector);
    if (state.visible && !fieldIsFinished(field, state)) return field;
  }
  if (guide.action && readField(guide.action.selector).visible) return guide.action;
  return null;
}

export type TourOffer = 'offer' | 'not_needed' | 'none';

/**
 * Whether the dashboard should offer the walkthrough.
 *
 * Only the offer card: once answered it stays answered. Starting the walkthrough
 * again does not depend on this (see showComposerNextStep and the Get-started card).
 *
 * `undefined` means /auth/me has not answered, so nothing is decided on it. Staff
 * cannot add products, so they are not offered a tour they could not finish, and
 * nothing is saved for them.
 */
export function tourOffer(
  status: FirstInvoiceTourStatus | null | undefined,
  companyRole: UserProfile['role'] | null,
  metrics: Pick<DashboardMetrics, 'sales'> | null,
): TourOffer {
  if (status !== null || !metrics) return 'none';
  if (hasPostedInvoices(metrics)) return 'not_needed';
  return companyRole === 'admin' || companyRole === 'manager' ? 'offer' : 'none';
}

export function canStartTour(companyRole: UserProfile['role'] | null): boolean {
  return companyRole === 'admin' || companyRole === 'manager';
}

/**
 * Whether the active company has any invoice at all (any year, cancelled and
 * purchases included). The active company's id follows this prefix.
 */
export const FIRST_INVOICE_QUERY_KEY = ['first-invoice-tour', 'company-has-invoice'] as const;

/** The composer's line for someone who left the walkthrough before their first invoice (#963). */
export const COMPOSER_NEXT_STEP = 'Next: pick your customer, add an item, then tap Create invoice.';

/**
 * Whether it is worth asking the server if the company has an invoice yet, so
 * the composer can offer the next step. Only while the walkthrough is unanswered
 * or was skipped: "completed" and "not_needed" both mean an invoice exists, and
 * `undefined` means /auth/me has not answered.
 */
export function mayNeedFirstInvoiceHelp(status: FirstInvoiceTourStatus | null | undefined): boolean {
  return status === null || status === 'skipped';
}

/**
 * Whether the composer shows the next-step line and "Show me how" (#963 §5):
 * a new sales invoice, for a company with no invoice yet, while the walkthrough
 * is not running. `hasInvoice` is null until that is known, which shows nothing.
 */
export function showComposerNextStep({
  tourRunning,
  hasInvoice,
  isNewSalesInvoice,
}: {
  tourRunning: boolean;
  hasInvoice: boolean | null;
  isNewSalesInvoice: boolean;
}): boolean {
  return !tourRunning && hasInvoice === false && isNewSalesInvoice;
}
