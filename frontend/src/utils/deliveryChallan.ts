import type {
  CompanyTermOut,
  DeliveryChallan,
  DeliveryChallanCreate,
  DeliveryChallanPurpose,
  DeliveryChallanStatus,
  Product,
} from '../types/api';
import { roundMoney } from './invoiceTotals';

export const CHALLAN_PURPOSES: { value: DeliveryChallanPurpose; label: string }[] = [
  { value: 'supply_on_approval', label: 'Supply on approval' },
  { value: 'job_work', label: 'Job work' },
  { value: 'liquid_gas', label: 'Supply of liquid gas (quantity not known)' },
  { value: 'skd_ckd_lots', label: 'SKD/CKD or in lots' },
  { value: 'exhibition', label: 'Exhibition or fair' },
  { value: 'own_use', label: 'For own use / branch transfer' },
  { value: 'other', label: 'Other' },
];

export const CHALLAN_PURPOSE_LABELS = Object.fromEntries(
  CHALLAN_PURPOSES.map((purpose) => [purpose.value, purpose.label]),
) as Record<DeliveryChallanPurpose, string>;

export const DEFAULT_CHALLAN_PURPOSE: DeliveryChallanPurpose = 'supply_on_approval';

export const CHALLAN_STATUS_LABELS: Record<DeliveryChallanStatus, string> = {
  open: 'Open',
  invoiced: 'Invoiced',
  cancelled: 'Cancelled',
};

/** The chips on the list, in the order someone working through them reads them. */
export const CHALLAN_STATUS_FILTERS: { value: DeliveryChallanStatus; label: string }[] = [
  { value: 'open', label: CHALLAN_STATUS_LABELS.open },
  { value: 'invoiced', label: CHALLAN_STATUS_LABELS.invoiced },
  { value: 'cancelled', label: CHALLAN_STATUS_LABELS.cancelled },
];

export const CHALLAN_COPY_LABELS = ['Original for consignee', 'Duplicate for transporter', 'Triplicate for consignor'] as const;
export const MAX_CHALLAN_COPIES = 3;

/** How long an open challan has been out, for the list: "1 day", "14 days". */
export function formatChallanAge(days: number): string {
  return `${days} ${days === 1 ? 'day' : 'days'}`;
}

export type ChallanAction = 'convert' | 'edit' | 'eway' | 'cancel';

/**
 * Which actions a challan offers, from its stored status. Mirrors the server's rules
 * so a closed challan shows no dead buttons; the server still decides.
 */
export function allowedChallanActions(challan: Pick<DeliveryChallan, 'status'>): ChallanAction[] {
  switch (challan.status) {
    case 'open':
      return ['convert', 'edit', 'eway', 'cancel'];
    case 'invoiced':
      return ['eway'];
    default:
      return [];
  }
}

/** The status chip colours the rest of the app already uses. */
export function challanStatusBadgeClass(status: DeliveryChallanStatus): string {
  switch (status) {
    case 'invoiced':
      return 'status-chip status-chip--success';
    case 'cancelled':
      return 'status-chip status-chip--cancelled';
    default:
      return 'status-chip';
  }
}

/** Rule 55: at most 16 characters, letters, digits, "-" and "/", starting with a letter or digit. Blank means auto. */
export function isValidChallanNumber(value: string): boolean {
  if (value === '') return true;
  return /^[A-Za-z0-9][A-Za-z0-9/-]{0,15}$/.test(value);
}

/** See the quotations list: a list that failed to load cannot claim there are none. */
export function showChallansEmptyState(list: { isLoading: boolean; isError: boolean; rowCount: number }): boolean {
  return !list.isLoading && !list.isError && list.rowCount === 0;
}

export function challanPdfFileName(challanNumber: string): string {
  return `delivery_challan_${challanNumber.replace(/\//g, '_')}.pdf`;
}

/* ------------------------------------------------------------------ form helpers */

export type ChallanLineForm = {
  id: number;
  productId: string;
  quantity: string;
  unitPrice: string;
  description: string;
};

export type ChallanFormState = {
  ledgerId: string;
  challanNumber: string;
  challanDate: string;
  purpose: DeliveryChallanPurpose;
  /** The state the user picked; empty means "use the default for this customer". */
  placeOfSupply: string;
  shippingSameAsBilling: boolean;
  /** '' = none chosen yet, '__new__' = typing a new address, else a saved address id. */
  shippingSelection: string;
  newShippingLabel: string;
  newShippingAddress: string;
  referenceNotes: string;
  termsText: string;
  items: ChallanLineForm[];
};

export function newChallanLine(id: number): ChallanLineForm {
  return { id, productId: '', quantity: '1', unitPrice: '', description: '' };
}

export function initialChallanForm(today: string, termsText = ''): ChallanFormState {
  return {
    ledgerId: '',
    challanNumber: '',
    challanDate: today,
    purpose: DEFAULT_CHALLAN_PURPOSE,
    placeOfSupply: '',
    shippingSameAsBilling: true,
    shippingSelection: '',
    newShippingLabel: '',
    newShippingAddress: '',
    referenceNotes: '',
    termsText,
    items: [newChallanLine(1)],
  };
}

/** The company's terms as one block, "1. First\n2. Second". */
export function termsToText(terms: Pick<CompanyTermOut, 'serial_number' | 'content'>[]): string {
  return [...terms]
    .sort((a, b) => a.serial_number - b.serial_number)
    .map((term) => `${term.serial_number}. ${term.content}`)
    .join('\n');
}

/** Products that may go on a challan: serial-numbered ones may not (yet). */
export function challanProducts<T extends Pick<Product, 'track_serials'>>(products: T[]): T[] {
  return products.filter((product) => !product.track_serials);
}

function parseNumber(value: string): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

/** Quantity times rate for one line, to the paisa. The price falls back to the product's. */
export function challanLineTaxable(
  line: Pick<ChallanLineForm, 'quantity' | 'unitPrice'>,
  product: Pick<Product, 'price'> | undefined,
): number {
  const price = line.unitPrice.trim() !== '' ? parseNumber(line.unitPrice) : (product?.price ?? 0);
  return roundMoney(parseNumber(line.quantity) * price);
}

export function challanTotalValue(
  lines: ChallanLineForm[],
  products: Pick<Product, 'id' | 'price'>[],
): number {
  return roundMoney(
    lines.reduce(
      (sum, line) => sum + challanLineTaxable(line, products.find((product) => String(product.id) === line.productId)),
      0,
    ),
  );
}

/** Rows saved on the challan, back into editable lines. */
export function challanToFormState(challan: DeliveryChallan): ChallanFormState {
  return {
    ledgerId: String(challan.ledger_id),
    challanNumber: challan.challan_number,
    challanDate: challan.challan_date,
    purpose: challan.purpose,
    placeOfSupply: challan.place_of_supply ?? '',
    shippingSameAsBilling: !challan.shipping_address,
    // A saved address that has since been deleted leaves its text on the challan; edit it as a new one.
    shippingSelection: challan.shipping_address_id ? String(challan.shipping_address_id) : (challan.shipping_address ? '__new__' : ''),
    newShippingLabel: challan.shipping_address_label ?? '',
    newShippingAddress: challan.shipping_address ?? '',
    referenceNotes: challan.reference_notes ?? '',
    termsText: challan.terms_text ?? '',
    items: challan.items.length
      ? challan.items.map((item, index) => ({
          id: index + 1,
          productId: String(item.product_id),
          quantity: String(item.quantity),
          unitPrice: String(item.unit_price),
          description: item.description ?? '',
        }))
      : [newChallanLine(1)],
  };
}

/** The first thing wrong with the form, in the words the page shows, or null. */
export function validateChallanForm(form: ChallanFormState): string | null {
  if (!form.ledgerId) return 'Choose the customer this challan goes to.';
  if (!isValidChallanNumber(form.challanNumber.trim())) {
    return 'The challan number can have at most 16 characters: letters, digits, "-" and "/", starting with a letter or digit.';
  }
  if (!form.challanDate) return 'Choose the challan date.';
  const filled = form.items.filter((line) => line.productId);
  if (filled.length === 0) return 'Add at least one item.';
  for (const line of form.items) {
    if (!line.productId) return 'Pick a product on every line, or remove the empty line.';
    if (!(parseNumber(line.quantity) > 0)) return 'Every line needs a quantity above zero.';
    if (line.unitPrice.trim() !== '' && parseNumber(line.unitPrice) < 0) return 'A rate cannot be negative.';
  }
  if (!form.shippingSameAsBilling && (form.shippingSelection === '' || form.shippingSelection === '__new__') && !form.newShippingAddress.trim()) {
    return 'Enter the shipping address, or tick "Ship to the billing address".';
  }
  return null;
}

/**
 * The request body for the form. `placeOfSupply` is the resolved state code
 * ('' when the company has no GSTIN). Blank optional text goes as null so an
 * edit can clear it.
 */
export function buildChallanPayload(form: ChallanFormState, placeOfSupply: string): DeliveryChallanCreate {
  const payload: DeliveryChallanCreate = {
    ledger_id: Number(form.ledgerId),
    challan_number: form.challanNumber.trim() || null,
    challan_date: form.challanDate,
    purpose: form.purpose,
    place_of_supply: placeOfSupply || null,
    reference_notes: form.referenceNotes.trim() || null,
    terms_text: form.termsText.trim() || '',
    items: form.items.map((line) => ({
      product_id: Number(line.productId),
      quantity: parseNumber(line.quantity),
      unit_price: line.unitPrice.trim() === '' ? null : parseNumber(line.unitPrice),
      description: line.description.trim() || null,
    })),
  };
  if (form.shippingSameAsBilling) {
    payload.shipping_address_same_as_billing = true;
  } else if (form.shippingSelection !== '' && form.shippingSelection !== '__new__') {
    payload.shipping_address_same_as_billing = false;
    payload.shipping_address_id = Number(form.shippingSelection);
  } else {
    payload.shipping_address_same_as_billing = false;
    payload.new_shipping_address = {
      label: form.newShippingLabel.trim() || 'Shipping address',
      address: form.newShippingAddress.trim(),
    };
  }
  return payload;
}

export function challanSavedMessage(number: string, editing: boolean): string {
  return editing
    ? `Delivery challan ${number} updated. Stock has been adjusted.`
    : `Delivery challan ${number} saved. Stock has been reduced.`;
}

export function challanCancelledMessage(number: string): string {
  return `Delivery challan ${number} cancelled. Its goods are back in stock.`;
}

/** What the form page hands the list page through router state. */
export type ChallanListState = { success?: string; openId?: number };

export function readChallanListState(state: unknown): ChallanListState {
  if (!state || typeof state !== 'object') return {};
  const { success, openId } = state as Record<string, unknown>;
  return {
    success: typeof success === 'string' ? success : undefined,
    openId: typeof openId === 'number' ? openId : undefined,
  };
}

/**
 * The id in /delivery-challans/:id/edit, or null on the new-challan route. A
 * malformed id comes back as NaN, so the page can refuse it without a request.
 */
export function parseChallanRouteId(raw: string | undefined): number | null {
  if (raw === undefined) return null;
  return /^[1-9]\d*$/.test(raw) ? Number(raw) : Number.NaN;
}

export type ChallanFormView = 'loading' | 'form' | 'not-editable' | 'load-failed';

/**
 * What the form page shows. When editing, the form appears only once the open
 * challan is loaded: a failed or impossible load must not leave an empty
 * "new challan" form whose Save would PUT to an id that does not exist.
 */
export function challanFormView(input: {
  editingId: number | null;
  loading: boolean;
  challanFailed: boolean;
  status?: DeliveryChallanStatus;
}): ChallanFormView {
  const { editingId, loading, challanFailed, status } = input;
  if (editingId === null) return loading ? 'loading' : 'form';
  if (Number.isNaN(editingId) || challanFailed) return 'load-failed';
  if (loading || !status) return 'loading';
  return status === 'open' ? 'form' : 'not-editable';
}

/**
 * Place of supply only matters to a GST-registered seller, as on the invoice form.
 * Without a company GSTIN it always resolves to "", so a select would not hold a pick.
 */
export function showChallanPlaceOfSupply(companyGst: string | null | undefined): boolean {
  return Boolean(companyGst?.trim());
}
