import { useQuery } from '@tanstack/react-query';
import api from '../api/client';
import {
  canStartTour,
  COMPOSER_NEXT_STEP,
  FIRST_INVOICE_QUERY_KEY,
  mayNeedFirstInvoiceHelp,
  showComposerNextStep,
} from '../features/firstInvoiceTour/tourSteps';
import { useAuthStore } from '../store/useAuthStore';
import { activeCompanyId } from '../utils/getStarted';
import { useFirstInvoiceTourStore } from '../store/useFirstInvoiceTourStore';

/** The line itself, and "Show me how" for people who can finish the walkthrough. */
export function ComposerNextStepHint({ onShowMeHow }: { onShowMeHow?: () => void }) {
  return (
    <div className="composer-next-step" data-testid="composer-next-step">
      <p className="field-hint composer-next-step__line">{COMPOSER_NEXT_STEP}</p>
      {onShowMeHow ? (
        <button type="button" className="link-button link-button--tap composer-next-step__action" onClick={onShowMeHow}>
          Show me how
        </button>
      ) : null}
    </div>
  );
}

/**
 * After "Exit walkthrough" the composer used to say nothing about what to do
 * next, and the walkthrough could not be started again (#963 §5). While the
 * company has no invoice and the walkthrough is not running, this says what is
 * next and offers to start it again.
 */
export default function ComposerNextStep({ isNewSalesInvoice }: { isNewSalesInvoice: boolean }) {
  const status = useAuthStore((state) => state.firstInvoiceTourStatus);
  const companyRole = useAuthStore((state) => state.companyRole);
  const userEmail = useAuthStore((state) => state.userEmail);
  const phase = useFirstInvoiceTourStore((state) => state.phase);
  const owner = useFirstInvoiceTourStore((state) => state.owner);
  const start = useFirstInvoiceTourStore((state) => state.start);
  const tourRunning = phase === 'running' && owner === userEmail;

  const hasInvoiceQuery = useQuery({
    queryKey: [...FIRST_INVOICE_QUERY_KEY, activeCompanyId()],
    queryFn: async () => {
      const response = await api.get<{ total: number }>('/invoices/', {
        params: { page: 1, page_size: 1, show_cancelled: true },
      });
      return response.data.total > 0;
    },
    enabled: isNewSalesInvoice && mayNeedFirstInvoiceHelp(status),
  });

  const show = showComposerNextStep({
    tourRunning,
    hasInvoice: hasInvoiceQuery.data ?? null,
    isNewSalesInvoice,
  });
  if (!show) return null;

  return <ComposerNextStepHint onShowMeHow={canStartTour(companyRole) ? start : undefined} />;
}
