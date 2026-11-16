import { useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { Ban, FileText, Pencil, Plus, Truck } from 'lucide-react';
import { getApiErrorMessage } from '../api/client';
import ConfirmDialog from '../components/ConfirmDialog';
import DeliveryChallanPreview from '../components/DeliveryChallanPreview';
import DeliveryChallansTable from '../components/DeliveryChallansTable';
import EmptyState from '../components/EmptyState';
import EwayBillModal from '../components/EwayBillModal';
import LoadingState from '../components/LoadingState';
import type { PreviewAction } from '../components/PreviewToolbar';
import SearchInput from '../components/SearchInput';
import StatusToasts from '../components/StatusToasts';
import {
  cancelDeliveryChallan,
  fetchDeliveryChallanById,
  fetchDeliveryChallans,
} from '../features/deliveryChallans/api';
import { deliveryChallanQueryKeys } from '../features/deliveryChallans/queryKeys';
import type { DeliveryChallan, DeliveryChallanStatus } from '../types/api';
import {
  CHALLAN_STATUS_FILTERS,
  CHALLAN_STATUS_LABELS,
  allowedChallanActions,
  challanCancelledMessage,
  readChallanListState,
  showChallansEmptyState,
} from '../utils/deliveryChallan';
import { formatDate } from '../utils/formatting';

const PAGE_SIZE = 20;

function readStatus(value: string | null): DeliveryChallanStatus | undefined {
  return CHALLAN_STATUS_FILTERS.some((chip) => chip.value === value) ? (value as DeliveryChallanStatus) : undefined;
}

export default function DeliveryChallansPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const status = readStatus(searchParams.get('status'));
  const search = searchParams.get('search') ?? '';
  const page = Math.max(1, Number(searchParams.get('page')) || 1);

  const [previewing, setPreviewing] = useState<DeliveryChallan | null>(null);
  const [cancelling, setCancelling] = useState<DeliveryChallan | null>(null);
  const [ewayFor, setEwayFor] = useState<DeliveryChallan | null>(null);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  const filters = useMemo(() => ({ page, pageSize: PAGE_SIZE, search, status }), [page, search, status]);
  const listQuery = useQuery({
    queryKey: deliveryChallanQueryKeys.list(filters),
    queryFn: () => fetchDeliveryChallans(filters),
    // Cancelling or restoring an invoice, on another page, changes these statuses.
    refetchOnMount: 'always',
  });
  const counts = listQuery.data?.status_counts ?? {};

  // The form page hands over a success message and the challan it just saved. Read it
  // once, then clear it so a refresh does not show the toast again.
  const handedOver = useRef(false);
  useEffect(() => {
    if (handedOver.current) return;
    const { success: message, openId } = readChallanListState(location.state);
    if (message === undefined && openId === undefined) return;
    handedOver.current = true;
    if (message) setSuccess(message);
    navigate(`${location.pathname}${location.search}`, { replace: true, state: null });
    if (openId !== undefined) {
      fetchDeliveryChallanById(openId)
        .then(setPreviewing)
        .catch((err) => setError(getApiErrorMessage(err, 'Unable to open the delivery challan')));
    }
  }, [location.state, location.pathname, location.search, navigate]);

  function setFilter(key: string, value: string | undefined) {
    setSearchParams((previous) => {
      const next = new URLSearchParams(previous);
      if (value) next.set(key, value);
      else next.delete(key);
      if (key !== 'page') next.delete('page');
      return next;
    }, { replace: true });
  }

  const cancelMutation = useMutation({
    mutationFn: (challan: DeliveryChallan) => cancelDeliveryChallan(challan.id),
    onSuccess: async (updated) => {
      setCancelling(null);
      setError('');
      setSuccess(challanCancelledMessage(updated.challan_number));
      setPreviewing((current) => (current && current.id === updated.id ? updated : current));
      await queryClient.invalidateQueries({ queryKey: deliveryChallanQueryKeys.all });
    },
    onError: (err) => {
      setCancelling(null);
      setError(getApiErrorMessage(err, 'Unable to cancel the delivery challan'));
    },
  });

  function convert(challan: DeliveryChallan) {
    navigate(`/invoices?from_challan=${challan.id}`);
  }

  function menuActionsFor(challan: DeliveryChallan): PreviewAction[] {
    const allowed = allowedChallanActions(challan);
    const actions: PreviewAction[] = [];
    if (allowed.includes('convert')) {
      actions.push({
        label: 'Convert to invoice',
        icon: <FileText size={16} aria-hidden="true" />,
        onClick: () => convert(challan),
      });
    }
    if (allowed.includes('edit')) {
      actions.push({
        label: 'Edit',
        icon: <Pencil size={16} aria-hidden="true" />,
        onClick: () => navigate(`/delivery-challans/${challan.id}/edit`),
      });
    }
    if (allowed.includes('eway')) {
      actions.push({
        label: 'E-Way Bill',
        icon: <Truck size={16} aria-hidden="true" />,
        onClick: () => setEwayFor(challan),
      });
    }
    if (allowed.includes('cancel')) {
      actions.push({
        label: 'Cancel challan',
        icon: <Ban size={16} aria-hidden="true" />,
        onClick: () => setCancelling(challan),
      });
    }
    return actions;
  }

  const rows = listQuery.data?.items ?? [];
  const noFilters = !status && !search;

  return (
    <div className="page-grid">
      <section className="page-hero">
        <div>
          <p className="eyebrow">Sales</p>
          <h1 className="page-title">Delivery Challans</h1>
          <p className="section-copy">
            Goods sent to a customer before the bill. Saving a challan takes the goods out of stock; converting it makes the tax invoice.
          </p>
        </div>
        <div className="button-row">
          <Link className="button button--primary" to="/delivery-challans/new">
            <Plus size={14} /> New delivery challan
          </Link>
        </div>
      </section>

      <StatusToasts
        error={error || (listQuery.error ? getApiErrorMessage(listQuery.error, 'Unable to load delivery challans') : '')}
        success={success}
        onClearError={() => setError('')}
        onClearSuccess={() => setSuccess('')}
      />

      <section className="content-grid content-grid--single">
        <article className="panel stack">
          <div className="button-row" style={{ flexWrap: 'wrap' }} role="group" aria-label="Filter by status">
            <button
              type="button"
              className={`button ${!status ? 'button--secondary' : 'button--ghost'}`}
              aria-pressed={!status}
              onClick={() => setFilter('status', undefined)}
            >
              All
            </button>
            {CHALLAN_STATUS_FILTERS.map((chip) => (
              <button
                key={chip.value}
                type="button"
                className={`button ${status === chip.value ? 'button--secondary' : 'button--ghost'}`}
                aria-pressed={status === chip.value}
                data-testid={`challan-filter-${chip.value}`}
                onClick={() => setFilter('status', chip.value)}
              >
                {chip.label}{counts[chip.value] ? ` (${counts[chip.value]})` : ''}
              </button>
            ))}
          </div>

          <div className="field-grid">
            <div className="field">
              <SearchInput
                id="challan-search"
                label="Search delivery challans"
                wrapperClassName="ledger-search"
                inputClassName="input ledger-search__input"
                iconClassName="ledger-search__icon"
                clearClassName="ledger-search__clear"
                value={search}
                onChange={(value) => setFilter('search', value || undefined)}
                placeholder="Number or party"
              />
            </div>
          </div>

          {listQuery.isLoading ? <LoadingState message="Loading delivery challans…" /> : null}

          {showChallansEmptyState({ isLoading: listQuery.isLoading, isError: listQuery.isError, rowCount: rows.length }) ? (
            <EmptyState
              message={noFilters
                ? 'No delivery challans yet. A challan records goods sent to a customer before the bill; it takes them out of stock until you invoice or cancel it.'
                : 'Nothing matches these filters. Try a different status or search.'}
            />
          ) : null}

          {rows.length > 0 ? (
            <DeliveryChallansTable challans={rows} onOpen={setPreviewing} onConvert={convert} />
          ) : null}

          {listQuery.data && listQuery.data.total_pages > 1 ? (
            <div className="button-row" style={{ justifyContent: 'flex-end' }}>
              <button type="button" className="button button--ghost" disabled={page <= 1} onClick={() => setFilter('page', String(page - 1))}>
                Previous
              </button>
              <span className="muted-text">Page {page} of {listQuery.data.total_pages}</span>
              <button type="button" className="button button--ghost" disabled={page >= listQuery.data.total_pages} onClick={() => setFilter('page', String(page + 1))}>
                Next
              </button>
            </div>
          ) : null}
        </article>
      </section>

      {previewing ? (
        <DeliveryChallanPreview
          challan={previewing}
          menuActions={menuActionsFor(previewing)}
          meta={
            <>
              {formatDate(previewing.challan_date)}
              {' · '}
              {previewing.purpose_label}
              {' · '}
              {CHALLAN_STATUS_LABELS[previewing.status]}
              {previewing.invoice_number ? ` · Invoice ${previewing.invoice_number}` : ''}
            </>
          }
          onClose={() => setPreviewing(null)}
          onError={setError}
        />
      ) : null}

      {ewayFor ? (
        <EwayBillModal
          challan={{ id: ewayFor.id, challan_number: ewayFor.challan_number }}
          onClose={() => setEwayFor(null)}
        />
      ) : null}

      {cancelling ? (
        <ConfirmDialog
          title={`Cancel ${cancelling.challan_number}?`}
          message="Its goods are added back to stock. It stays on the list as cancelled and keeps its number. This cannot be undone."
          confirmText="Cancel challan"
          cancelText="Keep it"
          danger
          confirmDisabled={cancelMutation.isPending}
          onConfirm={() => cancelMutation.mutate(cancelling)}
          onCancel={() => setCancelling(null)}
        />
      ) : null}
    </div>
  );
}
