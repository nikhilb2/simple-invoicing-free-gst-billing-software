type PdfPrintFrame = { readonly contentWindow: Pick<Window, 'focus' | 'print'> | null };

/** Open the fetched PDF when the browser cannot print its embedded viewer. */
export function printPdf(frame: PdfPrintFrame | null, pdfUrl: string | null): void {
  if (!pdfUrl) return;

  try {
    const viewer = frame?.contentWindow;
    if (viewer && typeof viewer.print === 'function') {
      viewer.focus();
      viewer.print();
      return;
    }
  } catch {
    // Mobile PDF viewers can deny access to print, even for our own blob URL.
  }

  // Keep this synchronous with the click so the browser permits the new tab.
  window.open(pdfUrl, '_blank', 'noopener,noreferrer');
}
