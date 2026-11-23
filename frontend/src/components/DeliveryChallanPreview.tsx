import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { Download, ExternalLink, Printer } from 'lucide-react';
import { useEscapeClose } from '../hooks/useEscapeClose';
import { fetchDeliveryChallanPdf } from '../features/deliveryChallans/api';
import CopiesStepper from './CopiesStepper';
import PaperSizePicker from './PaperSizePicker';
import { usePaperChoice } from '../hooks/usePaperChoice';
import PreviewToolbar, { type PreviewAction } from './PreviewToolbar';
import type { DeliveryChallan } from '../types/api';
import { MAX_CHALLAN_COPIES, challanPdfFileName } from '../utils/deliveryChallan';

type DeliveryChallanPreviewProps = {
  challan: DeliveryChallan;
  /** Convert, edit, e-way bill and cancel, behind the "…" menu. The page owns what they do. */
  menuActions?: PreviewAction[];
  meta?: ReactNode;
  onClose: () => void;
  onError?: (message: string) => void;
};

export default function DeliveryChallanPreview({ challan, menuActions = [], meta, onClose, onError }: DeliveryChallanPreviewProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [copies, setCopies] = useState(1);
  const [paper, setPaper, requestPaper] = usePaperChoice();
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [loadingPdf, setLoadingPdf] = useState(true);
  const [pdfError, setPdfError] = useState('');
  const [previewFailed, setPreviewFailed] = useState(false);
  const iframeRef = useRef<HTMLIFrameElement | null>(null);

  const title = `Delivery Challan ${challan.challan_number}`;

  useEscapeClose(useCallback(() => {
    if (menuOpen) { setMenuOpen(false); return; }
    onClose();
  }, [menuOpen, onClose]));

  useEffect(() => {
    let isMounted = true;
    let objectUrlToRevoke: string | null = null;

    (async () => {
      setLoadingPdf(true);
      setPdfError('');
      setPdfUrl(null);
      setPreviewFailed(false);
      try {
        const blob = await fetchDeliveryChallanPdf(challan.id, copies, 'Unable to load PDF preview', requestPaper);
        const nextUrl = window.URL.createObjectURL(blob);
        objectUrlToRevoke = nextUrl;
        if (!isMounted) {
          window.URL.revokeObjectURL(nextUrl);
          return;
        }
        setPdfUrl(nextUrl);
      } catch (err) {
        if (!isMounted) return;
        const message = err instanceof Error ? err.message : 'Unable to load PDF preview';
        setPdfError(message);
        onError?.(message);
      } finally {
        if (isMounted) setLoadingPdf(false);
      }
    })();

    return () => {
      isMounted = false;
      if (objectUrlToRevoke) window.URL.revokeObjectURL(objectUrlToRevoke);
    };
    // The status is in the key: the PDF prints a mark when it is cancelled.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [challan.id, challan.status, copies, requestPaper]);

  const handleDownload = async () => {
    try {
      const blob = await fetchDeliveryChallanPdf(challan.id, copies, 'Unable to download PDF', requestPaper);
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = challanPdfFileName(challan.challan_number);
      link.click();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      onError?.(err instanceof Error ? err.message : 'Unable to download PDF');
    }
  };

  const handleOpenInNewTab = () => {
    if (pdfUrl) window.open(pdfUrl, '_blank', 'noopener,noreferrer');
  };

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true" aria-labelledby="challan-preview-title">
      <div className="modal-panel modal-panel--invoice-preview">
        <PreviewToolbar
          eyebrow="Delivery challan preview"
          titleId="challan-preview-title"
          title={title}
          meta={meta}
          primary={{
            label: 'Download',
            icon: <Download size={16} aria-hidden="true" />,
            onClick: handleDownload,
            title: 'Download delivery challan PDF',
          }}
          secondary={[
            {
              label: 'Print',
              icon: <Printer size={16} aria-hidden="true" />,
              onClick: () => {
                iframeRef.current?.contentWindow?.focus();
                iframeRef.current?.contentWindow?.print();
              },
              disabled: !pdfUrl || loadingPdf || previewFailed,
              title: 'Print delivery challan',
            },
          ]}
          menuExtra={<><CopiesStepper value={copies} onChange={setCopies} max={MAX_CHALLAN_COPIES} /><PaperSizePicker value={paper} onChange={setPaper} /></>}
          menu={[
            ...menuActions,
            {
              label: 'Open in new tab',
              icon: <ExternalLink size={16} aria-hidden="true" />,
              onClick: handleOpenInNewTab,
              disabled: !pdfUrl,
            },
          ]}
          menuOpen={menuOpen}
          onMenuOpenChange={setMenuOpen}
          onClose={onClose}
          closeLabel="Close delivery challan preview"
        />

        <div className="invoice-pdf-viewer" aria-live="polite">
          {loadingPdf ? <p className="muted-text">Loading PDF preview...</p> : null}
          {!loadingPdf && pdfError ? <p className="error-text">{pdfError}</p> : null}
          {!loadingPdf && previewFailed && pdfUrl ? (
            <div style={{ display: 'grid', gap: '10px', justifyItems: 'center', textAlign: 'center', padding: '16px' }}>
              <p className="muted-text">PDF preview is unavailable in this browser.</p>
              <button
                type="button"
                className="button button--primary"
                onClick={handleOpenInNewTab}
                title="Open PDF in a new browser tab"
                aria-label="Open PDF in a new browser tab"
              >
                Open in New Tab
              </button>
            </div>
          ) : null}
          {!loadingPdf && pdfUrl && !previewFailed ? (
            <iframe
              ref={iframeRef}
              title={`${title} PDF preview`}
              src={`${pdfUrl}#navpanes=0&toolbar=1&statusbar=0&messages=0`}
              className="invoice-pdf-viewer__frame"
              onError={() => {
                setPreviewFailed(true);
                onError?.('PDF preview failed. Open the PDF in a new tab.');
              }}
            />
          ) : null}
        </div>
      </div>
    </div>
  );
}
