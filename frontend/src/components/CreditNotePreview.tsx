import { useCallback, useEffect, useRef, useState } from 'react';
import { Ban, Download, ExternalLink, Printer, Share2 } from 'lucide-react';
import { useEscapeClose } from '../hooks/useEscapeClose';
import api, { getApiErrorMessage } from '../api/client';
import ShareModal from './ShareModal';
import PreviewToolbar from './PreviewToolbar';
import PaperSizePicker from './PaperSizePicker';
import { usePaperChoice } from '../hooks/usePaperChoice';
import { noteDocumentFileName, type NoteDocumentLabel } from '../utils/noteDocument';
import { printPdf } from '../utils/printPdf';

type CreditNotePreviewProps = {
  creditNoteId: number;
  creditNoteNumber?: string | null;
  /** An inward note prints, downloads and shares as our Debit Note. */
  documentLabel?: NoteDocumentLabel;
  /** A cancelled note can still be viewed and downloaded, but not shared. */
  canShare?: boolean;
  /** The customer's phone as stored — free text, and often absent. */
  ledgerPhone?: string | null;
  /** Named in the WhatsApp message so the customer knows who sent it. */
  companyName?: string | null;
  /** Offered in the menu on an active note; the page asks for confirmation. */
  onCancelNote?: () => void;
  cancelling?: boolean;
  onClose: () => void;
  onError?: (message: string) => void;
};

export default function CreditNotePreview({
  creditNoteId,
  creditNoteNumber,
  documentLabel = 'Credit Note',
  canShare = true,
  ledgerPhone,
  companyName,
  onCancelNote,
  cancelling = false,
  onClose,
  onError,
}: CreditNotePreviewProps) {
  const [showShareModal, setShowShareModal] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [paper, setPaper, requestPaper] = usePaperChoice();
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [loadingPdf, setLoadingPdf] = useState(true);
  const [pdfError, setPdfError] = useState('');
  const [previewFailed, setPreviewFailed] = useState(false);
  // "credit note" mid-sentence, "Credit note" at the start of one.
  const noun = documentLabel.toLowerCase();
  const nounAtStart = documentLabel.charAt(0) + noun.slice(1);
  const iframeRef = useRef<HTMLIFrameElement | null>(null);

  // The share modal stacked on top closes itself on Escape; without this guard
  // the same keypress tears down the preview behind it as well.
  useEscapeClose(useCallback(() => {
    if (menuOpen) { setMenuOpen(false); return; }
    if (!showShareModal) onClose();
  }, [menuOpen, showShareModal, onClose]));

  useEffect(() => {
    let isMounted = true;
    let objectUrlToRevoke: string | null = null;

    const loadPdf = async () => {
      setLoadingPdf(true);
      setPdfError('');
      setPdfUrl(null);
      setPreviewFailed(false);

      try {
        const response = await api.get(`/credit-notes/${creditNoteId}/pdf`, {
          params: { paper: requestPaper },
          responseType: 'blob',
        });
        const nextUrl = window.URL.createObjectURL(response.data as Blob);
        objectUrlToRevoke = nextUrl;

        if (!isMounted) {
          window.URL.revokeObjectURL(nextUrl);
          return;
        }
        setPdfUrl(nextUrl);
      } catch (err) {
        if (!isMounted) return;
        const message = getApiErrorMessage(err, `Unable to load ${noun} PDF preview`);
        setPdfError(message);
        onError?.(message);
      } finally {
        if (isMounted) {
          setLoadingPdf(false);
        }
      }
    };

    loadPdf();

    return () => {
      isMounted = false;
      if (objectUrlToRevoke) {
        window.URL.revokeObjectURL(objectUrlToRevoke);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [creditNoteId, requestPaper]);

  const handleDownloadPdf = async () => {
    try {
      const response = await api.get(`/credit-notes/${creditNoteId}/pdf`, {
        params: { paper: requestPaper },
        responseType: 'blob',
      });
      const url = window.URL.createObjectURL(response.data as Blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = noteDocumentFileName(documentLabel, creditNoteNumber, creditNoteId);
      link.click();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      onError?.(getApiErrorMessage(err, 'Unable to download PDF'));
    }
  };

  const handlePrintPdf = () => {
    printPdf(iframeRef.current, pdfUrl);
  };

  const handleOpenInNewTab = () => {
    if (!pdfUrl) return;
    window.open(pdfUrl, '_blank', 'noopener,noreferrer');
  };

  const label = creditNoteNumber || `#${creditNoteId}`;

  const downloadAction = {
    label: 'Download',
    icon: <Download size={16} aria-hidden="true" />,
    onClick: handleDownloadPdf,
    title: `Download ${noun} PDF`,
  };

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true" aria-labelledby="credit-note-preview-title">
      <div className="modal-panel modal-panel--invoice-preview">
        <PreviewToolbar
          menuExtra={<PaperSizePicker value={paper} onChange={setPaper} />}
          eyebrow={`${nounAtStart} preview`}
          titleId="credit-note-preview-title"
          title={`${documentLabel} ${label}`}
          primary={canShare ? {
            label: 'Share',
            icon: <Share2 size={16} aria-hidden="true" />,
            onClick: () => setShowShareModal(true),
            title: `Share a link to this ${noun}`,
          } : downloadAction}
          secondary={[
            {
              label: 'Print',
              icon: <Printer size={16} aria-hidden="true" />,
              onClick: handlePrintPdf,
              disabled: !pdfUrl || loadingPdf || previewFailed,
              title: `Print ${noun}`,
            },
            ...(canShare ? [downloadAction] : []),
          ]}
          menu={[
            {
              label: 'Open in new tab',
              icon: <ExternalLink size={16} aria-hidden="true" />,
              onClick: handleOpenInNewTab,
              disabled: !pdfUrl,
            },
            ...(onCancelNote ? [{
              label: cancelling ? 'Cancelling...' : 'Cancel credit note',
              icon: <Ban size={16} aria-hidden="true" />,
              onClick: onCancelNote,
              disabled: cancelling,
              title: `Cancel this ${noun}`,
            }] : []),
          ]}
          menuOpen={menuOpen}
          onMenuOpenChange={setMenuOpen}
          onClose={onClose}
          closeLabel={`Close ${noun} preview`}
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
              title={`${nounAtStart} ${label} PDF preview`}
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

      {showShareModal ? (
        <ShareModal
          resourceType="credit_note"
          resourceId={creditNoteId}
          label={`${documentLabel} ${label}`}
          messageLead={`${documentLabel} ${label}${companyName ? ` from ${companyName}` : ''}`}
          phone={ledgerPhone}
          onClose={() => setShowShareModal(false)}
        />
      ) : null}
    </div>
  );
}
