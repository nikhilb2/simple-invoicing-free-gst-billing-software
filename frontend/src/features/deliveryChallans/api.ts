import api, { cleanParams, getBlobErrorMessage } from '../../api/client';
import type {
  DeliveryChallan,
  DeliveryChallanConversionDraft,
  DeliveryChallanConvert,
  DeliveryChallanCreate,
  DeliveryChallanPurpose,
  DeliveryChallanStatus,
  DeliveryChallanUpdate,
  Invoice,
  PaginatedDeliveryChallans,
} from '../../types/api';

export type DeliveryChallanListFilters = {
  page: number;
  pageSize: number;
  search: string;
  status?: DeliveryChallanStatus;
  purpose?: DeliveryChallanPurpose;
};

export async function fetchDeliveryChallans(filters: DeliveryChallanListFilters): Promise<PaginatedDeliveryChallans> {
  const res = await api.get<PaginatedDeliveryChallans>('/delivery-challans/', {
    params: cleanParams({
      page: filters.page,
      page_size: filters.pageSize,
      search: filters.search,
      status: filters.status,
      purpose: filters.purpose,
    }),
  });
  return res.data;
}

export async function fetchDeliveryChallanById(id: number): Promise<DeliveryChallan> {
  const res = await api.get<DeliveryChallan>(`/delivery-challans/${id}`);
  return res.data;
}

export async function createDeliveryChallan(payload: DeliveryChallanCreate): Promise<DeliveryChallan> {
  const res = await api.post<DeliveryChallan>('/delivery-challans/', payload);
  return res.data;
}

export async function updateDeliveryChallan(id: number, payload: DeliveryChallanUpdate): Promise<DeliveryChallan> {
  const res = await api.put<DeliveryChallan>(`/delivery-challans/${id}`, payload);
  return res.data;
}

export async function cancelDeliveryChallan(id: number): Promise<DeliveryChallan> {
  const res = await api.post<DeliveryChallan>(`/delivery-challans/${id}/cancel`);
  return res.data;
}

export async function fetchChallanConversionDraft(id: number): Promise<DeliveryChallanConversionDraft> {
  const res = await api.get<DeliveryChallanConversionDraft>(`/delivery-challans/${id}/conversion-draft`);
  return res.data;
}

export async function convertDeliveryChallan(id: number, payload: DeliveryChallanConvert): Promise<Invoice> {
  const res = await api.post<Invoice>(`/delivery-challans/${id}/convert`, payload);
  return res.data;
}

/**
 * The PDF of a delivery challan. A failure arrives as a Blob (the request is
 * `responseType: 'blob'`), so it is decoded and thrown as an Error carrying the
 * server's own message.
 */
export async function fetchDeliveryChallanPdf(id: number, copies: number, fallback: string): Promise<Blob> {
  try {
    const response = await api.get(`/delivery-challans/${id}/pdf`, { params: { copies }, responseType: 'blob' });
    return response.data as Blob;
  } catch (err) {
    throw new Error(await getBlobErrorMessage(err, fallback));
  }
}
