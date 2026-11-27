import { useQuery } from '@tanstack/react-query';
import api from '../../api/client';
import { activeCompanyId } from '../../utils/getStarted';
import { FIRST_INVOICE_QUERY_KEY } from './tourSteps';

/**
 * Whether the active company has any invoice at all (any year, cancelled and
 * purchases included). `undefined` while loading or if the lookup failed. The
 * composer sets this to true when it saves an invoice.
 */
export function useCompanyHasInvoice(enabled = true): boolean | undefined {
  const query = useQuery({
    queryKey: [...FIRST_INVOICE_QUERY_KEY, activeCompanyId()],
    queryFn: async () => {
      const response = await api.get<{ total: number }>('/invoices/', {
        params: { page: 1, page_size: 1, show_cancelled: true },
      });
      return response.data.total > 0;
    },
    enabled,
  });
  return query.data;
}
