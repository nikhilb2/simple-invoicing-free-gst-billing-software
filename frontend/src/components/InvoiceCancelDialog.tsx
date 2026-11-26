import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import api, { getApiErrorMessage } from '../api/client';
import ConfirmDialog from './ConfirmDialog';
import StatusToasts from './StatusToasts';
import { useInvoiceCancelStore } from '../store/useInvoiceCancelStore';
import { invoiceQueryKeys } from '../features/invoices/queryKeys';
import { invoiceCancelConfirmMessage, invoiceToastMessage } from '../utils/invoiceToast';

export default function InvoiceCancelDialog() {
  const {
    pendingCancelId,
    pendingCancelNumber,
    pendingCancelLines,
    pendingCancelProducts,
    pendingCancelVoucherType,
    dismissCancel,
  } = useInvoiceCancelStore();
  const queryClient = useQueryClient();
  const [success, setSuccess] = useState('');
  const [error, setError] = useState('');

  const cancelMutation = useMutation({
    mutationFn: ({ id }: { id: number; message: string }) => api.delete(`/invoices/${id}`),
    onSuccess: (_res, { message }) => {
      setSuccess(message);
      void queryClient.invalidateQueries({ queryKey: invoiceQueryKeys.all });
    },
    onError: (err) => setError(getApiErrorMessage(err, 'Unable to cancel invoice')),
  });

  function handleConfirm() {
    if (pendingCancelId === null) return;
    dismissCancel();
    cancelMutation.mutate({
      id: pendingCancelId,
      message: invoiceToastMessage({
        action: 'cancel',
        voucherType: pendingCancelVoucherType ?? undefined,
        number: pendingCancelNumber,
        lines: pendingCancelLines,
        products: pendingCancelProducts,
      }),
    });
  }

  const label = pendingCancelNumber ?? (pendingCancelId ? `#${pendingCancelId}` : null);

  return (
    <>
      {pendingCancelId !== null && (
        <ConfirmDialog
          title="Cancel invoice"
          message={invoiceCancelConfirmMessage({
            number: label,
            voucherType: pendingCancelVoucherType,
            lines: pendingCancelLines,
            products: pendingCancelProducts,
          })}
          confirmText="Cancel invoice"
          onConfirm={handleConfirm}
          onCancel={dismissCancel}
        />
      )}
      <StatusToasts
        success={success}
        error={error}
        onClearSuccess={() => setSuccess('')}
        onClearError={() => setError('')}
      />
    </>
  );
}
