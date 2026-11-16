import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { Plus, Trash2 } from 'lucide-react';
import { getApiErrorMessage } from '../api/client';
import LedgerCombobox from '../components/LedgerCombobox';
import LoadingState from '../components/LoadingState';
import PlaceOfSupplyField from '../components/PlaceOfSupplyField';
import ProductCombobox from '../components/ProductCombobox';
import StatusToasts from '../components/StatusToasts';
import {
  createDeliveryChallan,
  fetchDeliveryChallanById,
  updateDeliveryChallan,
} from '../features/deliveryChallans/api';
import { deliveryChallanQueryKeys } from '../features/deliveryChallans/queryKeys';
import {
  fetchCompanyProfile,
  fetchLedgerAddresses,
  fetchLedgers,
  fetchProducts,
} from '../features/invoices/api';
import {
  CHALLAN_PURPOSES,
  buildChallanPayload,
  challanLineTaxable,
  challanProducts,
  challanSavedMessage,
  challanToFormState,
  challanTotalValue,
  challanFormView,
  initialChallanForm,
  newChallanLine,
  parseChallanRouteId,
  showChallanPlaceOfSupply,
  termsToText,
  validateChallanForm,
  type ChallanFormState,
  type ChallanLineForm,
} from '../utils/deliveryChallan';
import { toIsoDate } from '../utils/dateRanges';
import formatCurrency from '../utils/formatting';
import { resolvePlaceOfSupply, type PlaceOfSupplyChoice } from '../utils/gstStates';
import type { DeliveryChallanPurpose } from '../types/api';

export default function DeliveryChallanFormPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const params = useParams<{ id: string }>();
  const editingId = parseChallanRouteId(params.id);
  const isEditing = editingId !== null;
  const validEditingId = isEditing && !Number.isNaN(editingId);

  const [form, setForm] = useState<ChallanFormState>(() => initialChallanForm(toIsoDate(new Date())));
  const [placeChoice, setPlaceChoice] = useState<PlaceOfSupplyChoice | null>(null);
  const [error, setError] = useState('');
  const nextLineId = useRef(2);
  const loadedFor = useRef<number | 'new' | null>(null);

  const productsQuery = useQuery({ queryKey: ['challan-form', 'products'], queryFn: fetchProducts });
  const ledgersQuery = useQuery({ queryKey: ['challan-form', 'ledgers'], queryFn: fetchLedgers });
  const companyQuery = useQuery({ queryKey: ['challan-form', 'company'], queryFn: fetchCompanyProfile });
  const challanQuery = useQuery({
    queryKey: deliveryChallanQueryKeys.detail(editingId ?? 0),
    queryFn: () => fetchDeliveryChallanById(editingId as number),
    enabled: validEditingId,
    refetchOnMount: 'always',
  });
  const addressesQuery = useQuery({
    queryKey: ['challan-form', 'addresses', form.ledgerId],
    queryFn: () => fetchLedgerAddresses(Number(form.ledgerId)),
    enabled: Boolean(form.ledgerId),
  });

  const products = useMemo(() => challanProducts(productsQuery.data ?? []), [productsQuery.data]);
  const ledgers = ledgersQuery.data ?? [];
  const company = companyQuery.data;
  const addresses = addressesQuery.data ?? [];
  const selectedLedger = ledgers.find((ledger) => String(ledger.id) === form.ledgerId);

  // Editing: fill the form from the saved challan, once per challan.
  const challan = challanQuery.data;
  useEffect(() => {
    if (!isEditing || !challan || challan.status !== 'open' || loadedFor.current === challan.id) return;
    loadedFor.current = challan.id;
    const state = challanToFormState(challan);
    nextLineId.current = state.items.length + 1;
    setForm(state);
    if (challan.place_of_supply) {
      setPlaceChoice({ ledgerId: String(challan.ledger_id), code: challan.place_of_supply });
    }
  }, [isEditing, challan]);

  // New challan: start the terms from the company's own, once.
  useEffect(() => {
    if (isEditing || !company || loadedFor.current === 'new') return;
    loadedFor.current = 'new';
    setForm((current) => ({ ...current, termsText: current.termsText || termsToText(company.terms ?? []) }));
  }, [isEditing, company]);

  const placeOfSupply = resolvePlaceOfSupply(placeChoice, form.ledgerId, company?.gst, selectedLedger?.gst);
  const total = challanTotalValue(form.items, products);
  const currencyCode = company?.currency_code || 'INR';

  function patch(update: Partial<ChallanFormState>) {
    setForm((current) => ({ ...current, ...update }));
  }

  function updateLine(id: number, update: Partial<ChallanLineForm>) {
    setForm((current) => ({
      ...current,
      items: current.items.map((line) => (line.id === id ? { ...line, ...update } : line)),
    }));
  }

  function addLine() {
    const id = nextLineId.current++;
    setForm((current) => ({ ...current, items: [...current.items, newChallanLine(id)] }));
  }

  function removeLine(id: number) {
    setForm((current) => ({
      ...current,
      items: current.items.length > 1 ? current.items.filter((line) => line.id !== id) : current.items,
    }));
  }

  const saveMutation = useMutation({
    mutationFn: () => {
      const payload = buildChallanPayload(form, placeOfSupply);
      return isEditing ? updateDeliveryChallan(editingId as number, payload) : createDeliveryChallan(payload);
    },
    onSuccess: async (saved) => {
      await queryClient.invalidateQueries({ queryKey: deliveryChallanQueryKeys.all });
      // Stock moved: any product list the app holds is out of date.
      await queryClient.invalidateQueries({ queryKey: ['products'] });
      navigate('/delivery-challans', {
        state: { success: challanSavedMessage(saved.challan_number, isEditing), openId: saved.id },
      });
    },
    onError: (err) => setError(getApiErrorMessage(err, 'Unable to save the delivery challan')),
  });

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const problem = validateChallanForm(form);
    if (problem) {
      setError(problem);
      return;
    }
    setError('');
    saveMutation.mutate();
  }

  const loading = productsQuery.isLoading || ledgersQuery.isLoading || companyQuery.isLoading
    || (validEditingId && challanQuery.isLoading);
  const view = challanFormView({
    editingId,
    loading,
    challanFailed: challanQuery.isError,
    status: challan?.status,
  });
  const loadError = challanQuery.error || productsQuery.error || ledgersQuery.error || companyQuery.error;
  const heading = isEditing ? `Edit ${challan?.challan_number ?? 'delivery challan'}` : 'New delivery challan';

  return (
    <div className="page-grid">
      <section className="page-hero">
        <div>
          <p className="eyebrow">Delivery challans</p>
          <h1 className="page-title">{heading}</h1>
          <p className="section-copy">
            Goods leave stock when you save. It is not a bill: no tax is charged and nothing reaches your books until you convert it to an invoice.
          </p>
        </div>
      </section>

      <StatusToasts
        error={error || (loadError ? getApiErrorMessage(loadError, 'Unable to load the form') : '')}
        onClearError={() => setError('')}
        onClearSuccess={() => {}}
      />

      <section className="content-grid content-grid--single">
        <article className="panel stack">
          {view === 'loading' ? <LoadingState message="Loading…" /> : null}

          {view === 'load-failed' ? (
            <div className="stack">
              <p className="error-text" role="alert">
                {challanQuery.isError
                  ? 'This delivery challan could not be loaded, so it cannot be edited.'
                  : 'This delivery challan link is not valid.'}
              </p>
              <Link className="button button--ghost" to="/delivery-challans">Back to delivery challans</Link>
            </div>
          ) : null}

          {view === 'not-editable' ? (
            <div className="stack">
              <p className="error-text" role="alert">
                {challan?.status === 'invoiced'
                  ? 'An invoiced delivery challan cannot be edited.'
                  : 'A cancelled delivery challan cannot be edited.'}
              </p>
              <Link className="button button--ghost" to="/delivery-challans">Back to delivery challans</Link>
            </div>
          ) : null}

          {view === 'form' ? (
            <form className="stack" onSubmit={handleSubmit}>
              <div className="field-grid">
                <div className="field">
                  <label htmlFor="challan-ledger">Customer</label>
                  <LedgerCombobox
                    id="challan-ledger"
                    ledgers={ledgers}
                    value={form.ledgerId}
                    onChange={(ledgerId) => patch({ ledgerId, shippingSelection: '', newShippingLabel: '', newShippingAddress: '' })}
                    required
                  />
                </div>
                <div className="field">
                  <label htmlFor="challan-number">Challan number</label>
                  <input
                    id="challan-number"
                    className="input"
                    type="text"
                    maxLength={16}
                    value={form.challanNumber}
                    onChange={(event) => patch({ challanNumber: event.target.value })}
                    placeholder="Auto (next in series)"
                  />
                  <p className="muted-text" style={{ marginBottom: 0 }}>
                    Leave blank to use the next number. Up to 16 characters.
                  </p>
                </div>
                <div className="field">
                  <label htmlFor="challan-date">Challan date</label>
                  <input
                    id="challan-date"
                    className="input"
                    type="date"
                    value={form.challanDate}
                    onChange={(event) => patch({ challanDate: event.target.value })}
                    required
                  />
                </div>
                <div className="field">
                  <label htmlFor="challan-purpose">Purpose</label>
                  <select
                    id="challan-purpose"
                    className="select"
                    value={form.purpose}
                    onChange={(event) => patch({ purpose: event.target.value as DeliveryChallanPurpose })}
                  >
                    {CHALLAN_PURPOSES.map((purpose) => (
                      <option key={purpose.value} value={purpose.value}>{purpose.label}</option>
                    ))}
                  </select>
                </div>
                {showChallanPlaceOfSupply(company?.gst) ? (
                  <PlaceOfSupplyField
                    id="challan-place-of-supply"
                    value={placeOfSupply}
                    onChange={(code) => setPlaceChoice({ ledgerId: form.ledgerId, code })}
                  />
                ) : null}
              </div>

              <div className="field">
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '8px' }}>
                  <input
                    id="challan-ship-same"
                    type="checkbox"
                    checked={form.shippingSameAsBilling}
                    onChange={(event) => patch({
                      shippingSameAsBilling: event.target.checked,
                      ...(event.target.checked ? { shippingSelection: '', newShippingLabel: '', newShippingAddress: '' } : {}),
                    })}
                  />
                  <label htmlFor="challan-ship-same" style={{ marginBottom: 0, cursor: 'pointer' }}>
                    Ship to the billing address
                  </label>
                </div>

                {!form.shippingSameAsBilling ? (
                  <div className="stack" style={{ gap: '8px' }}>
                    {addresses.length > 0 ? (
                      <div className="field" style={{ marginBottom: 0 }}>
                        <label htmlFor="challan-shipping-address">Saved addresses</label>
                        <select
                          id="challan-shipping-address"
                          className="select"
                          value={form.shippingSelection}
                          onChange={(event) => {
                            const value = event.target.value;
                            const found = addresses.find((address) => String(address.id) === value);
                            patch({
                              shippingSelection: value,
                              newShippingLabel: found ? found.label : '',
                              newShippingAddress: found ? found.address : '',
                            });
                          }}
                        >
                          <option value="">-- Select saved address --</option>
                          {addresses.map((address) => (
                            <option key={address.id} value={address.id}>
                              {address.label} — {address.address.slice(0, 50)}{address.address.length > 50 ? '…' : ''}
                            </option>
                          ))}
                          <option value="__new__">+ Enter new address</option>
                        </select>
                      </div>
                    ) : null}

                    {form.shippingSelection === '__new__' || addresses.length === 0 ? (
                      <>
                        <div className="field" style={{ marginBottom: 0 }}>
                          <label htmlFor="challan-new-shipping-label">Address label</label>
                          <input
                            id="challan-new-shipping-label"
                            className="input"
                            type="text"
                            value={form.newShippingLabel}
                            onChange={(event) => patch({ newShippingLabel: event.target.value })}
                            placeholder="e.g. Warehouse, Site A"
                          />
                        </div>
                        <div className="field" style={{ marginBottom: 0 }}>
                          <label htmlFor="challan-new-shipping-address">Shipping address</label>
                          <textarea
                            id="challan-new-shipping-address"
                            className="input"
                            rows={3}
                            value={form.newShippingAddress}
                            onChange={(event) => patch({ newShippingAddress: event.target.value })}
                            placeholder="Full shipping / delivery address"
                          />
                          <p className="muted-text" style={{ marginBottom: 0 }}>
                            This address will be saved to the ledger for future use.
                          </p>
                        </div>
                      </>
                    ) : null}
                  </div>
                ) : null}
              </div>

              <div className="stack">
                <div className="line-items__header">
                  <p className="eyebrow" style={{ margin: 0 }}>Line items</p>
                </div>
                <p className="field-hint">Serial-numbered products can&apos;t go on a delivery challan yet.</p>
                {form.items.map((line, index) => {
                  const n = index + 1;
                  const product = products.find((candidate) => String(candidate.id) === line.productId);
                  const unit = product?.unit || '';
                  const allowDecimal = Boolean(product?.allow_decimal);
                  return (
                    <div key={line.id} className="line-item">
                      <div className="field">
                        <label htmlFor={`challan-product-${n}`}>Line {n}</label>
                        <ProductCombobox
                          id={`challan-product-${n}`}
                          products={products}
                          value={line.productId}
                          onChange={(productId, picked) => updateLine(line.id, {
                            productId,
                            unitPrice: String(picked.price),
                          })}
                          required
                        />
                      </div>

                      <div className="field">
                        <label htmlFor={`challan-quantity-${n}`}>Qty{unit ? ` (${unit})` : ''}</label>
                        <input
                          id={`challan-quantity-${n}`}
                          className="input"
                          type="number"
                          min={allowDecimal ? '0.001' : '1'}
                          step={allowDecimal ? '0.001' : '1'}
                          value={line.quantity}
                          onChange={(event) => updateLine(line.id, { quantity: event.target.value })}
                          required
                        />
                      </div>

                      <div className="field">
                        <label htmlFor={`challan-price-${n}`}>Rate</label>
                        <input
                          id={`challan-price-${n}`}
                          className="input"
                          type="number"
                          step="0.01"
                          min="0"
                          value={line.unitPrice}
                          onChange={(event) => updateLine(line.id, { unitPrice: event.target.value })}
                          placeholder={product ? String(product.price) : '0.00'}
                        />
                      </div>

                      <div className="line-item__price">
                        <span className="line-item__label">Taxable value</span>
                        <div className="line-item__price-value">
                          <span>{formatCurrency(challanLineTaxable(line, product), currencyCode)}</span>
                          <span className="table-subtext">
                            {product ? `HSN ${product.hsn_sac || '—'} · GST ${product.gst_rate}%` : 'HSN — · GST —'}
                          </span>
                        </div>
                      </div>

                      <button
                        type="button"
                        className="button button--danger button--icon"
                        onClick={() => removeLine(line.id)}
                        disabled={form.items.length === 1}
                        title={`Remove line ${n}`}
                        aria-label={`Remove line ${n}`}
                      >
                        <Trash2 size={15} />
                      </button>

                      <div className="field field--full">
                        <label htmlFor={`challan-description-${n}`}>Description (optional)</label>
                        <textarea
                          id={`challan-description-${n}`}
                          className="input"
                          rows={1}
                          value={line.description}
                          onChange={(event) => updateLine(line.id, { description: event.target.value })}
                          placeholder="Batch code, box number, or item notes"
                        />
                      </div>
                    </div>
                  );
                })}
                <div className="button-row">
                  <button type="button" className="button button--ghost" onClick={addLine} disabled={products.length === 0}>
                    <Plus size={14} /> Add line
                  </button>
                </div>
              </div>

              <p className="section-copy" data-testid="challan-total">
                <strong>Total value</strong>: {formatCurrency(total, currencyCode)}
              </p>

              <div className="field-grid">
                <div className="field">
                  <label htmlFor="challan-notes">Notes</label>
                  <textarea
                    id="challan-notes"
                    className="input"
                    rows={3}
                    value={form.referenceNotes}
                    onChange={(event) => patch({ referenceNotes: event.target.value })}
                  />
                </div>
                <div className="field">
                  <label htmlFor="challan-terms">Terms &amp; conditions</label>
                  <textarea
                    id="challan-terms"
                    className="input"
                    rows={3}
                    value={form.termsText}
                    onChange={(event) => patch({ termsText: event.target.value })}
                  />
                </div>
              </div>

              <div className="button-row">
                <button type="submit" className="button button--primary" disabled={saveMutation.isPending}>
                  {saveMutation.isPending ? 'Saving…' : 'Save challan'}
                </button>
                <Link className="button button--secondary" to="/delivery-challans">Cancel</Link>
              </div>
            </form>
          ) : null}
        </article>
      </section>
    </div>
  );
}
