import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { FilePlus2, Plus } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import { cancelCreditNote, createCreditNote, listCreditNotes } from '../api/creditNotes';
import api, { getApiErrorMessage } from '../api/client';
import CreditNotePreview from '../components/CreditNotePreview';
import ConfirmDialog from '../components/ConfirmDialog';
import { noteDocumentLabel } from '../utils/noteDocument';
import LedgerCombobox from '../components/LedgerCombobox';
import StatusToasts from '../components/StatusToasts';
import EmptyState from '../components/EmptyState';
import LoadingState from '../components/LoadingState';
import ModalCloseButton from '../components/ModalCloseButton';
import SearchInput from '../components/SearchInput';
import { useEscapeClose } from '../hooks/useEscapeClose';
import useDebouncedValue from '../hooks/useDebouncedValue';
import { focusAfterCancelDialog } from '../utils/creditNoteCancelFocus';
import CreditNotesList from './credit-notes/CreditNotesList';
import { invoiceCreditStatusMeta } from '../common/invoiceCreditStatus';
import type {
  CompanyProfile,
  CreditNote,
  CreditNoteCreate,
  CreditNoteDirection,
  Invoice,
  PaginatedInvoices,
  PaginatedLedgers,
  PaginatedProducts,
  Ledger,
  Product,
} from '../types/api';
import formatCurrency, { formatDate, plural } from '../utils/formatting';
import { roundMoney } from '../utils/invoiceTotals';
import { backdatedNoteWarning, creditNoteDateChoice as nextCreditNoteDateChoice, shownCreditNoteDate } from '../utils/creditNoteDate';
import { creditNoteInvoiceLabels } from '../utils/creditNoteInvoices';
import { creditNoteCancelMessage } from '../utils/creditNoteCancelMessage';
import { billedLineAmounts, returnPreviewTotal } from '../utils/creditNoteAmounts';
import { toIsoDate } from '../utils/dateRanges';
import { exportCreditNotesCsv } from './credit-notes/exports';
import { numericParam, useDeepLinkScroll } from '../utils/deepLink';

type SelectedLineItem = {
  invoice: Invoice;
  item: Invoice['items'][number];
  productName: string;
  wholeQuantity: boolean;
  quantityKey: string;
};

const createCreditNoteTypeLabels: Record<'return' | 'discount', string> = {
  return: 'Goods came back',
  discount: 'Discount after billing',
};

function createQuantityKey(invoiceId: number, invoiceItemId: number) {
  return `${invoiceId}:${invoiceItemId}`;
}

export default function CreditNotesPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const queryLedgerId = searchParams.get('ledger') || '';
  const queryInvoiceId = searchParams.get('invoice') || '';

  const [company, setCompany] = useState<CompanyProfile | null>(null);
  const [ledgers, setLedgers] = useState<Ledger[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [allInvoices, setAllInvoices] = useState<Invoice[]>([]);
  const [creditNotes, setCreditNotes] = useState<CreditNote[]>([]);

  const [selectedLedgerId, setSelectedLedgerId] = useState(queryLedgerId);
  const [selectedInvoiceIds, setSelectedInvoiceIds] = useState<number[]>([]);
  const [creditNoteType, setCreditNoteType] = useState<'return' | 'discount'>('return');
  // Which way the note runs. Inward means the supplier issued it: we file
  // nothing, we record theirs and give back the input credit we claimed.
  const [direction, setDirection] = useState<CreditNoteDirection>('outward');
  const [supplierNoteNumber, setSupplierNoteNumber] = useState('');
  const [supplierNoteDate, setSupplierNoteDate] = useState('');
  // The date stays null until the user picks one, so the form sends none and the
  // server dates the note today in India. What it shows follows the clock.
  const [today, setToday] = useState(() => toIsoDate(new Date()));
  const [creditNoteDateChoice, setCreditNoteDateChoice] = useState<string | null>(null);
  const creditNoteDate = shownCreditNoteDate(creditNoteDateChoice, today);
  const [reason, setReason] = useState('');
  const [quantities, setQuantities] = useState<Record<string, string>>({});
  const [discountAmounts, setDiscountAmounts] = useState<Record<string, string>>({});

  const [loadingBootstrap, setLoadingBootstrap] = useState(true);
  const [loadingCreditNotes, setLoadingCreditNotes] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [cancellingId, setCancellingId] = useState<number | null>(null);
  const [cancelTarget, setCancelTarget] = useState<CreditNote | null>(null);
  const cancelInFlight = useRef(false);
  const [previewCreditNote, setPreviewCreditNote] = useState<CreditNote | null>(null);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [gstWarnings, setGstWarnings] = useState<string[]>([]);

  // The create form is a dialog. A deep link (?invoice= / ?ledger=) opens it at once.
  const [formOpen, setFormOpen] = useState(Boolean(queryLedgerId || queryInvoiceId));
  const hadDeepLink = useRef(Boolean(queryLedgerId || queryInvoiceId));
  const [showMoreFilters, setShowMoreFilters] = useState(false);
  const [counts, setCounts] = useState({ active: 0, cancelled: 0 });

  const [search, setSearch] = useState('');
  // The list and the status counts follow the debounced text, not each keystroke.
  const debouncedSearch = useDebouncedValue(search, 300);
  const [statusFilter, setStatusFilter] = useState('');
  const [directionFilter, setDirectionFilter] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [listPage, setListPage] = useState(1);
  const [listTotalPages, setListTotalPages] = useState(1);
  const [listTotal, setListTotal] = useState(0);
  const [refreshKey, setRefreshKey] = useState(0);
  const pageSize = 20;

  // Citation deep link: /credit-notes?cn_id=7. The feed searches on credit note
  // number and not on id, so the number is fetched first and dropped into the
  // search box — that filters the registry down to the one record, on any page
  // and whatever the other filters were left on.
  const deepLinkCreditNoteId = numericParam(searchParams, 'cn_id');
  const [highlightCreditNoteId, setHighlightCreditNoteId] = useState<number | null>(null);

  // A form left open overnight would otherwise still offer yesterday.
  useEffect(() => {
    const refreshToday = () => setToday(toIsoDate(new Date()));
    window.addEventListener('focus', refreshToday);
    document.addEventListener('visibilitychange', refreshToday);
    return () => {
      window.removeEventListener('focus', refreshToday);
      document.removeEventListener('visibilitychange', refreshToday);
    };
  }, []);

  const currencyCode = company?.currency_code || 'INR';
  const hasFilters = Boolean(search || statusFilter || directionFilter || dateFrom || dateTo);

  // A link to the form from another page while this one is open.
  useEffect(() => {
    if (queryLedgerId || queryInvoiceId) setFormOpen(true);
  }, [queryLedgerId, queryInvoiceId]);

  function openForm() {
    setFormOpen(true);
  }

  function closeForm() {
    if (submitting) return;
    setFormOpen(false);
    if (searchParams.has('ledger') || searchParams.has('invoice')) {
      const next = new URLSearchParams(searchParams);
      next.delete('ledger');
      next.delete('invoice');
      setSearchParams(next, { replace: true });
    }
  }

  // Read through a ref so the listener keeps one identity and never sees a stale closure.
  const escapeHandler = useRef(() => {});
  useEffect(() => {
    escapeHandler.current = () => {
      if (formOpen && !previewCreditNote) closeForm();
    };
  });
  useEscapeClose(useCallback(() => escapeHandler.current(), []));

  // Status chip counts follow the other filters but not the status itself.
  useEffect(() => {
    let cancelled = false;
    const base = {
      page_size: 1,
      search: debouncedSearch,
      direction: (directionFilter || undefined) as CreditNoteDirection | undefined,
      date_from: dateFrom || undefined,
      date_to: dateTo || undefined,
    };
    (async () => {
      try {
        const [active, cancelledRes] = await Promise.all([
          listCreditNotes({ ...base, status: 'active' }),
          listCreditNotes({ ...base, status: 'cancelled' }),
        ]);
        if (!cancelled) setCounts({ active: active.data.total, cancelled: cancelledRes.data.total });
      } catch {
        // The chips just keep their last numbers; the list reports its own errors.
      }
    })();
    return () => { cancelled = true; };
  }, [dateFrom, dateTo, directionFilter, refreshKey, debouncedSearch]);

  useEffect(() => {
    if (!cancelTarget) return;
    document.querySelector<HTMLButtonElement>('[aria-labelledby="confirm-dialog-title"] button')?.focus();
    return () => focusAfterCancelDialog(document, cancelTarget.id);
  }, [cancelTarget]);

  // A note only ever covers one voucher type, so the picker only ever offers
  // one. Mixing them was possible before and produced a note the ledger, the
  // stock and GSTR-1 each read differently.
  const expectedVoucherType = direction === 'inward' ? 'purchase' : 'sales';

  const fetchInvoices = useCallback(
    () => api.get<PaginatedInvoices>('/invoices/', {
      params: { page_size: 500, show_cancelled: false, voucher_type: expectedVoucherType },
    }),
    [expectedVoucherType],
  );

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        setLoadingBootstrap(true);
        const [companyRes, ledgersRes, productsRes, invoicesRes] = await Promise.all([
          api.get<CompanyProfile>('/company/'),
          api.get<PaginatedLedgers>('/ledgers/', { params: { page_size: 500 } }),
          api.get<PaginatedProducts>('/products/', { params: { page_size: 500 } }),
          fetchInvoices(),
        ]);

        if (cancelled) return;

        setCompany(companyRes.data);
        setLedgers(ledgersRes.data.items);
        setProducts(productsRes.data.items);
        setAllInvoices(invoicesRes.data.items);

        // This load runs again when the voucher type changes; keep the ledger
        // the user already picked and only default to the first one.
        const firstLedger = ledgersRes.data.items[0];
        if (!hadDeepLink.current && firstLedger) {
          setSelectedLedgerId((current) => current || String(firstLedger.id));
        }
      } catch (err) {
        if (!cancelled) {
          setError(getApiErrorMessage(err, 'Unable to load credit note workspace data'));
        }
      } finally {
        if (!cancelled) {
          setLoadingBootstrap(false);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [fetchInvoices]);

  useEffect(() => {
    if (!queryInvoiceId) return;
    let cancelled = false;

    (async () => {
      try {
        const invoiceRes = await api.get<Invoice>(`/invoices/${Number(queryInvoiceId)}`);
        if (cancelled) return;

        if (invoiceRes.data.ledger_id) {
          // Landing on a purchase invoice should open the Purchase tab, not
          // leave the user on Sales staring at an empty invoice list.
          setDirection(invoiceRes.data.voucher_type === 'purchase' ? 'inward' : 'outward');
          setSelectedLedgerId(String(invoiceRes.data.ledger_id));
          setSelectedInvoiceIds([invoiceRes.data.id]);
        }
      } catch (err) {
        if (!cancelled) {
          setError(getApiErrorMessage(err, 'Unable to preload invoice for credit note creation'));
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [queryInvoiceId]);

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        setLoadingCreditNotes(true);
        const response = await listCreditNotes({
          page: listPage,
          page_size: pageSize,
          search: debouncedSearch,
          status: statusFilter || undefined,
          direction: (directionFilter || undefined) as CreditNoteDirection | undefined,
          date_from: dateFrom || undefined,
          date_to: dateTo || undefined,
        });

        if (cancelled) return;

        setCreditNotes(response.data.items);
        setListTotal(response.data.total);
        setListTotalPages(response.data.total_pages);
      } catch (err) {
        if (!cancelled) {
          setError(getApiErrorMessage(err, 'Unable to load credit notes'));
        }
      } finally {
        if (!cancelled) {
          setLoadingCreditNotes(false);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [dateFrom, dateTo, directionFilter, listPage, refreshKey, debouncedSearch, statusFilter]);

  useEffect(() => {
    if (deepLinkCreditNoteId === null) return undefined;
    let cancelled = false;

    (async () => {
      try {
        const { data } = await api.get<CreditNote>(`/credit-notes/${deepLinkCreditNoteId}`);
        if (cancelled) return;
        setSearch(data.credit_note_number);
        setStatusFilter('');
        setDirectionFilter('');
        setDateFrom('');
        setDateTo('');
        setListPage(1);
        setHighlightCreditNoteId(data.id);
      } catch (err) {
        if (!cancelled) {
          setError(getApiErrorMessage(err, `Unable to open credit note #${deepLinkCreditNoteId}`));
        }
      }
    })();

    return () => { cancelled = true; };
  }, [deepLinkCreditNoteId]);

  // The table shows on desktop and the cards on a phone; the hidden one is a no-op.
  useDeepLinkScroll(
    highlightCreditNoteId === null ? null : `credit-note-${highlightCreditNoteId}`,
    !loadingCreditNotes,
  );
  useDeepLinkScroll(
    highlightCreditNoteId === null ? null : `credit-note-${highlightCreditNoteId}-card`,
    !loadingCreditNotes,
  );

  const filteredInvoices = useMemo(() => {
    const numericLedgerId = Number(selectedLedgerId);
    if (!numericLedgerId) return [];
    return allInvoices.filter((invoice) => (
      invoice.ledger_id === numericLedgerId
      && invoice.status === 'active'
      // The fetch already asks for one voucher type; this holds the line while
      // a switched tab's request is still in flight.
      && invoice.voucher_type === expectedVoucherType
    ));
  }, [allInvoices, expectedVoucherType, selectedLedgerId]);

  useEffect(() => {
    // Until the invoices have loaded every selection would look stale, which
    // dropped the invoice a deep link had just picked.
    if (!selectedLedgerId || loadingBootstrap) return;

    setSelectedInvoiceIds((current) => current.filter((invoiceId) =>
      filteredInvoices.some((invoice) => invoice.id === invoiceId)
    ));
    setQuantities((current) => {
      const allowedKeys = new Set(
        filteredInvoices.flatMap((invoice) => invoice.items.map((item) => createQuantityKey(invoice.id, item.id)))
      );
      return Object.fromEntries(Object.entries(current).filter(([key]) => allowedKeys.has(key)));
    });
    setDiscountAmounts((current) => {
      const allowedKeys = new Set(
        filteredInvoices.flatMap((invoice) => invoice.items.map((item) => createQuantityKey(invoice.id, item.id)))
      );
      return Object.fromEntries(Object.entries(current).filter(([key]) => allowedKeys.has(key)));
    });
  }, [filteredInvoices, loadingBootstrap, selectedLedgerId]);

  useEffect(() => {
    if (!selectedLedgerId || !formOpen) return;
    const currentLedgerId = searchParams.get('ledger') || '';
    const currentInvoiceId = searchParams.get('invoice') || '';
    const nextInvoiceId = selectedInvoiceIds.length === 1 ? String(selectedInvoiceIds[0]) : '';

    if (currentLedgerId === selectedLedgerId && currentInvoiceId === nextInvoiceId) {
      return;
    }

    const nextParams = new URLSearchParams(searchParams);
    nextParams.set('ledger', selectedLedgerId);
    if (nextInvoiceId) {
      nextParams.set('invoice', nextInvoiceId);
    } else {
      nextParams.delete('invoice');
    }
    setSearchParams(nextParams, { replace: true });
  }, [formOpen, searchParams, selectedInvoiceIds, selectedLedgerId, setSearchParams]);

  const selectedInvoiceMap = useMemo(() => new Set(selectedInvoiceIds), [selectedInvoiceIds]);

  const selectedLineItems = useMemo<SelectedLineItem[]>(() => {
    return filteredInvoices
      .filter((invoice) => selectedInvoiceMap.has(invoice.id))
      .flatMap((invoice) =>
        invoice.items.map((item) => {
          const matchedProduct = products.find((product) => product.id === item.product_id);
          return {
            invoice,
            item,
            productName: matchedProduct?.name || `Product #${item.product_id}`,
            wholeQuantity: matchedProduct?.allow_decimal === false || matchedProduct?.track_serials === true,
            quantityKey: createQuantityKey(invoice.id, item.id),
          };
        })
      );
  }, [filteredInvoices, products, selectedInvoiceMap]);

  const payloadItems = useMemo(() => {
    if (creditNoteType === 'discount') {
      return selectedLineItems
        .map((line) => ({
          invoice_id: line.invoice.id,
          invoice_item_id: line.item.id,
          discount_amount_inclusive: Number(discountAmounts[line.quantityKey] || 0),
        }))
        .filter((line) => Number.isFinite(line.discount_amount_inclusive) && line.discount_amount_inclusive > 0);
    }

    return selectedLineItems
      .map((line) => ({
        invoice_id: line.invoice.id,
        invoice_item_id: line.item.id,
        quantity: Number(quantities[line.quantityKey] || 0),
      }))
      .filter((line) => Number.isFinite(line.quantity) && line.quantity > 0);
  }, [creditNoteType, discountAmounts, quantities, selectedLineItems]);

  const previewTotal = useMemo(() => {
    if (creditNoteType === 'discount') {
      return selectedLineItems.reduce((sum, line) => {
        const discount = Number(discountAmounts[line.quantityKey] || 0);
        if (!Number.isFinite(discount) || discount <= 0) {
          return sum;
        }
        return sum + discount;
      }, 0);
    }

    // What the server will credit: each line's share after the invoice-level
    // discount and round-off, plus the TCS it reverses (#797).
    return returnPreviewTotal(selectedLineItems.map((line) => ({
      invoice: line.invoice,
      item: line.item,
      quantity: Number(quantities[line.quantityKey] || 0),
    })));
  }, [creditNoteType, discountAmounts, quantities, selectedLineItems]);

  // What each selected line billed, which is the most notes can credit against it.
  const billedLineTotals = useMemo(() => {
    const totals = new Map<string, number>();
    const invoices = new Map(selectedLineItems.map((line) => [line.invoice.id, line.invoice]));
    for (const invoice of invoices.values()) {
      for (const [itemId, line] of billedLineAmounts(invoice)) {
        totals.set(createQuantityKey(invoice.id, itemId), line.lineTotal);
      }
    }
    return totals;
  }, [selectedLineItems]);

  const discountPreviewSplit = useMemo(() => {
    if (creditNoteType !== 'discount') {
      return { taxable: 0, tax: 0 };
    }

    return selectedLineItems.reduce((acc, line) => {
      const discount = Number(discountAmounts[line.quantityKey] || 0);
      if (!Number.isFinite(discount) || discount <= 0) {
        return acc;
      }

      const gstRate = Number(line.item.gst_rate || 0);
      const taxable = gstRate > 0 ? roundMoney(discount / (1 + (gstRate / 100))) : roundMoney(discount);
      const tax = roundMoney(discount - taxable);

      return {
        taxable: roundMoney(acc.taxable + taxable),
        tax: roundMoney(acc.tax + tax),
      };
    }, { taxable: 0, tax: 0 });
  }, [creditNoteType, discountAmounts, selectedLineItems]);

  // Nothing is filed for an inward note, so its date moves no return.
  const backdatedWarning = direction === 'outward' ? backdatedNoteWarning(creditNoteDate, today) : null;

  function handleLedgerChange(nextLedgerId: string) {
    setSelectedLedgerId(nextLedgerId);
    setSelectedInvoiceIds([]);
    setQuantities({});
    setDiscountAmounts({});
    setReason('');
  }

  function handleToggleInvoice(invoiceId: number) {
    setSelectedInvoiceIds((current) => {
      if (current.includes(invoiceId)) {
        setQuantities((existing) => {
          const next = { ...existing };
          Object.keys(next)
            .filter((key) => key.startsWith(`${invoiceId}:`))
            .forEach((key) => delete next[key]);
          return next;
        });
        setDiscountAmounts((existing) => {
          const next = { ...existing };
          Object.keys(next)
            .filter((key) => key.startsWith(`${invoiceId}:`))
            .forEach((key) => delete next[key]);
          return next;
        });
        return current.filter((value) => value !== invoiceId);
      }
      return [...current, invoiceId];
    });
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!selectedLedgerId) {
      setError(direction === 'inward'
        ? 'Pick a supplier before creating a credit note.'
        : 'Pick a customer before creating a credit note.');
      return;
    }
    if (selectedInvoiceIds.length === 0) {
      setError('Select at least one invoice.');
      return;
    }
    if (payloadItems.length === 0) {
      setError(creditNoteType === 'discount' ? 'Enter at least one discount amount.' : 'Enter at least one quantity to give back.');
      return;
    }
    if (direction === 'inward' && (!supplierNoteNumber.trim() || !supplierNoteDate)) {
      setError("Enter the number and date on the supplier's credit note.");
      return;
    }

    const payload: CreditNoteCreate = {
      ledger_id: Number(selectedLedgerId),
      invoice_ids: selectedInvoiceIds,
      credit_note_type: creditNoteType,
      direction,
      supplier_credit_note_number: direction === 'inward' ? supplierNoteNumber.trim() : null,
      supplier_credit_note_date: direction === 'inward' ? supplierNoteDate : null,
      credit_note_date: creditNoteDateChoice,
      reason: reason.trim() || null,
      items: payloadItems,
    };

    try {
      setSubmitting(true);
      const response = await createCreditNote(payload);
      setGstWarnings((response.data.gst_warnings || []).map(
        (warning) => `${response.data.credit_note_number}: ${warning}`,
      ));
      setSuccess(
        direction === 'inward'
          ? `Supplier credit note ${supplierNoteNumber.trim()} recorded as ${response.data.credit_note_number}.`
          : `Credit note ${response.data.credit_note_number} created.`,
      );
      setReason('');
      setSelectedInvoiceIds([]);
      setQuantities({});
      setDiscountAmounts({});
      setSupplierNoteNumber('');
      setSupplierNoteDate('');
      setCreditNoteDateChoice(null);
      setRefreshKey((value) => value + 1);
      setFormOpen(false);
      const next = new URLSearchParams(searchParams);
      next.delete('ledger');
      next.delete('invoice');
      setSearchParams(next, { replace: true });
      setAllInvoices((await fetchInvoices()).data.items);
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to create credit note'));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleCancelCreditNote(creditNoteId: number) {
    if (cancelInFlight.current) return;
    cancelInFlight.current = true;
    try {
      setError('');
      setCancellingId(creditNoteId);
      const response = await cancelCreditNote(creditNoteId);
      setCreditNotes((current) => current.map((note) => note.id === creditNoteId ? response.data : note));
      setCancelTarget(null);
      setSuccess('Credit note cancelled.');
      setRefreshKey((value) => value + 1);
      setPreviewCreditNote(null);
      setAllInvoices((await fetchInvoices()).data.items);
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to cancel credit note'));
    } finally {
      cancelInFlight.current = false;
      setCancellingId(null);
    }
  }

  // Exports every note the current filters select, not just the visible
  // page: the export pages the list endpoint itself (see credit-notes/exports).
  async function handleExportCreditNotesCsv() {
    try {
      setExporting(true);
      setError('');
      await exportCreditNotesCsv(
        {
          search: search || undefined,
          status: statusFilter || undefined,
          direction: (directionFilter || undefined) as CreditNoteDirection | undefined,
          date_from: dateFrom || undefined,
          date_to: dateTo || undefined,
        },
        ledgers,
        allInvoices,
      );
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to export credit notes as CSV'));
    } finally {
      setExporting(false);
    }
  }

  return (
    <>
      <StatusToasts
        error={error}
        success={success}
        onClearError={() => setError('')}
        onClearSuccess={() => setSuccess('')}
      />
      {gstWarnings.length > 0 ? (
        <div className="panel stack" role="alert">
          {gstWarnings.map((warning) => <p className="field-warning" key={warning}>{warning}</p>)}
          <button type="button" className="button button--secondary button--small" onClick={() => setGstWarnings([])}>Dismiss GST warning</button>
        </div>
      ) : null}

      <div className="page-grid">
        <section className="page-hero">
          <div>
            <p className="eyebrow">Sales</p>
            <h1 className="page-title">Credit / Debit Notes</h1>
            <p className="section-copy">
              Money you give back to a customer when goods come back or you allow a discount after billing. Open a note to print or share it.
            </p>
          </div>
          <div className="button-row">
            <button type="button" className="button button--primary" onClick={openForm}>
              <Plus size={14} aria-hidden="true" /> New credit note
            </button>
            <button
              type="button"
              className="button button--secondary"
              disabled={loadingCreditNotes || exporting || creditNotes.length === 0}
              onClick={() => void handleExportCreditNotesCsv()}
            >
              {exporting ? 'Exporting...' : 'Export CSV'}
            </button>
          </div>
        </section>

        <section className="content-grid content-grid--single">
          <article className="panel stack">
            <div className="chip-row" role="group" aria-label="Filter by status">
              {([['', 'All', counts.active + counts.cancelled], ['active', 'Active', counts.active], ['cancelled', 'Cancelled', counts.cancelled]] as const).map(([value, label, count]) => (
                <button
                  key={value}
                  type="button"
                  className={`button ${statusFilter === value ? 'button--secondary' : 'button--ghost'}`}
                  aria-pressed={statusFilter === value}
                  onClick={() => { setStatusFilter(value); setListPage(1); }}
                >
                  {label} ({count})
                </button>
              ))}
            </div>

            <div className="field-grid">
              <div className="field">
                <SearchInput
                  id="credit-note-search"
                  label="Search credit notes"
                  wrapperClassName="ledger-search"
                  inputClassName="input ledger-search__input"
                  iconClassName="ledger-search__icon"
                  clearClassName="ledger-search__clear"
                  value={search}
                  onChange={(value) => { setSearch(value); setListPage(1); }}
                  placeholder="Number or customer"
                />
              </div>
            </div>

            <div>
              <button
                type="button"
                className="button button--ghost button--small"
                aria-expanded={showMoreFilters}
                onClick={() => setShowMoreFilters((open) => !open)}
              >
                More filters
              </button>
            </div>

            {showMoreFilters ? (
              <div className="field-grid">
                <label>
                  <span>Type</span>
                  <select
                    className="select"
                    value={directionFilter}
                    onChange={(event) => { setDirectionFilter(event.target.value); setListPage(1); }}
                  >
                    <option value="">All</option>
                    <option value="outward">Customer notes</option>
                    <option value="inward">Supplier notes</option>
                  </select>
                </label>
                <label>
                  <span>From</span>
                  <input className="input" type="date" value={dateFrom} onChange={(event) => { setDateFrom(event.target.value); setListPage(1); }} />
                </label>
                <label>
                  <span>To</span>
                  <input className="input" type="date" value={dateTo} onChange={(event) => { setDateTo(event.target.value); setListPage(1); }} />
                </label>
              </div>
            ) : null}

            <CreditNotesList
              notes={creditNotes}
              ledgers={ledgers}
              invoices={allInvoices}
              currencyCode={currencyCode}
              highlightId={highlightCreditNoteId}
              loading={loadingCreditNotes}
              hasFilters={hasFilters}
              page={listPage}
              totalPages={listTotalPages}
              total={listTotal}
              pageSize={pageSize}
              onPageChange={setListPage}
              onView={setPreviewCreditNote}
              onNew={openForm}
            />
          </article>
        </section>
      </div>

      {formOpen ? (
        <div className="modal-overlay">
          <div
            className="modal-panel modal-panel--credit-note-form"
            role="dialog"
            aria-modal="true"
            aria-labelledby="credit-note-form-title"
          >
            <div className="panel__header">
              <div>
                <p className="eyebrow">New</p>
                <h2 className="nav-panel__title" id="credit-note-form-title">New credit note</h2>
              </div>
              <div className="panel__header-actions">
                <div style={{ textAlign: 'right' }}>
                  <p className="eyebrow">Credit total</p>
                  <strong>{formatCurrency(previewTotal, currencyCode)}</strong>
                </div>
                <ModalCloseButton onClick={closeForm} label="Close credit note form" disabled={submitting} />
              </div>
            </div>

          {loadingBootstrap ? <LoadingState message="Loading customers, invoices, and products..." /> : null}

          {!loadingBootstrap ? (
            <form className="stack" onSubmit={handleSubmit}>
              <div className="field-grid">
                <label>
                  <span>This note is for *</span>
                  <select
                    id="credit-note-direction"
                    className="select"
                    value={direction}
                    onChange={(event) => {
                      setDirection(event.target.value as CreditNoteDirection);
                      setSelectedInvoiceIds([]);
                      setQuantities({});
                      setDiscountAmounts({});
                      setSupplierNoteNumber('');
                      setSupplierNoteDate('');
                    }}
                  >
                    <option value="outward">A customer (we give a credit)</option>
                    <option value="inward">A supplier (they gave us a credit)</option>
                  </select>
                </label>
                <label>
                  <span>{direction === 'inward' ? 'Supplier *' : 'Customer *'}</span>
                  <LedgerCombobox
                    id="credit-note-ledger"
                    ledgers={ledgers}
                    value={selectedLedgerId}
                    onChange={handleLedgerChange}
                    required
                  />
                </label>
                <label>
                  <span>What happened? *</span>
                  <select
                    className="select"
                    value={creditNoteType}
                    onChange={(event) => {
                      const nextType = event.target.value as 'return' | 'discount';
                      setCreditNoteType(nextType);
                      setQuantities({});
                      setDiscountAmounts({});
                    }}
                  >
                    {Object.entries(createCreditNoteTypeLabels).map(([value, label]) => (
                      <option key={value} value={value}>{label}</option>
                    ))}
                  </select>
                </label>
                <label>
                  <span>Date *</span>
                  <input
                    id="credit-note-date"
                    className="input"
                    type="date"
                    required
                    max={today}
                    value={creditNoteDate}
                    onChange={(event) => setCreditNoteDateChoice(nextCreditNoteDateChoice(event.target.value, today))}
                  />
                </label>
              </div>
              {backdatedWarning ? <p className="field-warning" role="alert">{backdatedWarning}</p> : null}

              {direction === 'inward' ? (
                <>
                  <p className="hint" style={{ margin: 0 }}>
                    Nothing is filed for this note — the supplier declares it and it reaches
                    you in GSTR-2B. Record their number and date so the two can be matched.
                  </p>
                  <div className="field-grid">
                    <label>
                      <span>Supplier credit note # *</span>
                      <input
                        id="credit-note-supplier-number"
                        className="input"
                        required
                        value={supplierNoteNumber}
                        onChange={(event) => setSupplierNoteNumber(event.target.value)}
                        placeholder="The number on their credit note"
                      />
                    </label>
                    <label>
                      <span>Supplier credit note date *</span>
                      <input
                        id="credit-note-supplier-date"
                        className="input"
                        type="date"
                        required
                        value={supplierNoteDate}
                        onChange={(event) => setSupplierNoteDate(event.target.value)}
                      />
                    </label>
                  </div>
                </>
              ) : null}

              <label>
                <span>Note (optional)</span>
                <textarea
                  className="textarea"
                  rows={3}
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  placeholder="For example: damaged goods"
                />
              </label>

              <div className="stack" style={{ gap: '12px' }}>
                <div className="panel" style={{ padding: '16px' }}>
                  <div className="panel__header">
                    <div>
                      <p className="eyebrow">Step 1</p>
                      <h3 className="nav-panel__title" style={{ fontSize: '1rem' }}>Pick the invoices</h3>
                    </div>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.9rem' }}>
                      {direction === 'inward'
                        ? `${filteredInvoices.length} purchase ${filteredInvoices.length === 1 ? 'bill' : 'bills'} from this supplier`
                        : `${filteredInvoices.length} ${filteredInvoices.length === 1 ? 'invoice' : 'invoices'} for this customer`}
                    </span>
                  </div>

                  {filteredInvoices.length === 0 ? (
                    <EmptyState message={direction === 'inward' ? 'This supplier has no bills to credit yet.' : 'This customer has no invoices to credit yet.'} />
                  ) : null}

                  <div className="stack" style={{ gap: '10px' }}>
                    {filteredInvoices.map((invoice) => {
                      const creditStatus = invoiceCreditStatusMeta[invoice.credit_status];
                      const checked = selectedInvoiceMap.has(invoice.id);
                      return (
                        <label
                          key={invoice.id}
                          style={{
                            display: 'flex',
                            gap: '12px',
                            padding: '12px',
                            border: checked ? '1px solid var(--accent)' : '1px solid var(--border)',
                            borderRadius: '12px',
                            alignItems: 'flex-start',
                            cursor: 'pointer',
                          }}
                        >
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={() => handleToggleInvoice(invoice.id)}
                            style={{ marginTop: '4px' }}
                          />
                          <div style={{ flex: 1 }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', flexWrap: 'wrap' }}>
                              <div>
                                <strong>{invoice.invoice_number || `#${invoice.id}`}</strong>
                                <p style={{ margin: '4px 0 0', color: 'var(--text-muted)' }}>Date {formatDate(invoice.invoice_date)} • {plural(invoice.items.length, 'item')}</p>
                              </div>
                              <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
                                <span style={{ padding: '4px 10px', borderRadius: '999px', background: creditStatus.background, color: creditStatus.color, fontSize: '0.8rem', fontWeight: 600 }}>
                                  {creditStatus.label}
                                </span>
                                <span style={{ fontWeight: 600 }}>{formatCurrency(invoice.total_amount, invoice.company_currency_code || currencyCode)}</span>
                              </div>
                            </div>
                            <p style={{ margin: '8px 0 0', color: 'var(--text-muted)' }}>
                              {(invoice.items || []).slice(0, 3).map((item) => {
                                const matchedProduct = products.find((product) => product.id === item.product_id);
                                return `${matchedProduct?.name || `Product #${item.product_id}`} x${item.quantity}`;
                              }).join(', ')}
                              {(invoice.items || []).length > 3 ? ' +' : ''}
                            </p>
                          </div>
                        </label>
                      );
                    })}
                  </div>
                </div>

                <div className="panel" style={{ padding: '16px' }}>
                  <div className="panel__header">
                    <div>
                      <p className="eyebrow">Step 2</p>
                      <h3 className="nav-panel__title" style={{ fontSize: '1rem' }}>
                        {creditNoteType === 'discount' ? 'Discount to give (incl. GST)' : 'How much to give back'}
                      </h3>
                    </div>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.9rem' }}>{plural(payloadItems.length, 'line')} selected</span>
                  </div>

                  {creditNoteType === 'discount' ? (
                    <p style={{ margin: '0 0 8px', color: 'var(--text-muted)' }}>
                      Auto split: Taxable {formatCurrency(discountPreviewSplit.taxable, currencyCode)} + Tax {formatCurrency(discountPreviewSplit.tax, currencyCode)}
                    </p>
                  ) : null}

                  {selectedLineItems.length === 0 ? <EmptyState message="Tick an invoice above to see its items." /> : null}

                  <div className="stack" style={{ gap: '10px' }}>
                    {selectedLineItems.map((line) => {
                      const discountAmount = Number(discountAmounts[line.quantityKey] || 0);
                      const gstRate = Number(line.item.gst_rate || 0);
                      const taxableSplit = gstRate > 0 ? roundMoney(discountAmount / (1 + (gstRate / 100))) : roundMoney(discountAmount);
                      const taxSplit = roundMoney(discountAmount - taxableSplit);
                      const billedLineTotal = billedLineTotals.get(line.quantityKey) ?? line.item.line_total;

                      return (
                      <div
                        key={line.quantityKey}
                        style={{
                          display: 'grid',
                          gridTemplateColumns: 'minmax(0, 2fr) 120px 120px',
                          gap: '12px',
                          alignItems: 'center',
                          border: '1px solid var(--border)',
                          borderRadius: '12px',
                          padding: '12px',
                        }}
                      >
                        <div>
                          <strong>{line.productName}</strong>
                          <p style={{ margin: '4px 0 0', color: 'var(--text-muted)' }}>
                            Invoice {line.invoice.invoice_number || `#${line.invoice.id}`} • Qty {line.item.quantity} • GST {line.item.gst_rate}%
                          </p>
                        </div>
                        <div>
                          <p style={{ margin: 0, color: 'var(--text-muted)', fontSize: '0.85rem' }}>Line total</p>
                          <strong>{formatCurrency(billedLineTotal, line.invoice.company_currency_code || currencyCode)}</strong>
                          {creditNoteType === 'discount' && discountAmount > 0 ? (
                            <p style={{ margin: '6px 0 0', color: 'var(--text-muted)', fontSize: '0.8rem' }}>
                              Split {formatCurrency(taxableSplit, line.invoice.company_currency_code || currencyCode)} + {formatCurrency(taxSplit, line.invoice.company_currency_code || currencyCode)}
                            </p>
                          ) : null}
                        </div>
                        <label>
                          <span style={{ display: 'block', marginBottom: '4px' }}>
                            {creditNoteType === 'discount' ? 'Discount (incl tax)' : 'Credit qty'}
                          </span>
                          <input
                            className="input"
                            type="number"
                            min={0}
                            max={creditNoteType === 'discount' ? billedLineTotal : line.item.quantity}
                            step={creditNoteType === 'discount' ? '0.01' : line.wholeQuantity ? '1' : '0.001'}
                            value={creditNoteType === 'discount' ? (discountAmounts[line.quantityKey] || '') : (quantities[line.quantityKey] || '')}
                            onChange={(event) => {
                              if (creditNoteType === 'discount') {
                                setDiscountAmounts((current) => ({
                                  ...current,
                                  [line.quantityKey]: event.target.value,
                                }));
                                return;
                              }

                              setQuantities((current) => ({
                                ...current,
                                [line.quantityKey]: event.target.value,
                              }));
                            }}
                            placeholder="0"
                          />
                        </label>
                      </div>
                      );
                    })}
                  </div>
                </div>
              </div>

              <div className="button-row">
                <button type="submit" className="button button--primary" disabled={submitting || !selectedLedgerId || payloadItems.length === 0}>
                  <FilePlus2 size={16} />
                  {submitting
                    ? (direction === 'inward' ? 'Saving...' : 'Creating...')
                    : (direction === 'inward' ? 'Save supplier credit note' : 'Create credit note')}
                </button>
                <button
                  type="button"
                  className="button button--secondary"
                  onClick={() => {
                    setSelectedInvoiceIds([]);
                    setQuantities({});
                    setDiscountAmounts({});
                    setReason('');
                    setCreditNoteType('return');
                    setDirection('outward');
                    setSupplierNoteNumber('');
                    setSupplierNoteDate('');
                    setCreditNoteDateChoice(null);
                  }}
                >
                  Reset form
                </button>
              </div>
            </form>
          ) : null}
          </div>
        </div>
      ) : null}

      {/* After the preview in the DOM, so the confirmation stacks above it. */}
      {previewCreditNote ? (
        <CreditNotePreview
          creditNoteId={previewCreditNote.id}
          creditNoteNumber={previewCreditNote.credit_note_number}
          documentLabel={noteDocumentLabel(previewCreditNote.direction)}
          canShare={previewCreditNote.status === 'active'}
          ledgerPhone={ledgers.find((entry) => entry.id === previewCreditNote.ledger_id)?.phone_number}
          companyName={company?.name}
          onClose={() => { if (!cancelTarget) setPreviewCreditNote(null); }}
          onError={(message) => setError(message)}
          onCancelNote={previewCreditNote.status === 'active' ? () => setCancelTarget(previewCreditNote) : undefined}
          cancelling={cancellingId === previewCreditNote.id}
        />
      ) : null}

      {cancelTarget ? (
        <ConfirmDialog
          title={`Cancel ${cancelTarget.credit_note_number}?`}
          message={creditNoteCancelMessage(
            cancelTarget,
            ledgers.find((ledger) => ledger.id === cancelTarget.ledger_id)?.name || (cancelTarget.direction === 'inward' ? 'this supplier' : 'this customer'),
            creditNoteInvoiceLabels(cancelTarget.invoice_ids, allInvoices),
            currencyCode,
          )}
          confirmText={cancellingId === cancelTarget.id ? 'Cancelling...' : 'Cancel credit note'}
          cancelText="Keep it"
          danger
          confirmDisabled={cancellingId !== null}
          onConfirm={() => void handleCancelCreditNote(cancelTarget.id)}
          onCancel={() => { if (!cancelInFlight.current) setCancelTarget(null); }}
        />
      ) : null}
    </>
  );
}
