import type { DeliveryChallanListFilters } from './api';

export const deliveryChallanQueryKeys = {
  all: ['delivery-challans'] as const,
  list: (filters: DeliveryChallanListFilters) => ['delivery-challans', 'list', filters] as const,
  detail: (id: number) => ['delivery-challans', 'detail', id] as const,
};
