import { afterEach, describe, expect, it, vi } from 'vitest';
import { printPdf } from './printPdf';

afterEach(() => vi.unstubAllGlobals());

describe('printPdf', () => {
  const url = 'blob:https://example.test/document';

  it('focuses and prints a supported viewer without opening another tab', () => {
    const open = vi.fn();
    vi.stubGlobal('window', { open });
    const viewer = { focus: vi.fn(), print: vi.fn() };
    printPdf({ contentWindow: viewer }, url);
    expect(viewer.focus).toHaveBeenCalledOnce();
    expect(viewer.print).toHaveBeenCalledOnce();
    expect(viewer.print.mock.instances[0]).toBe(viewer);
    expect(open).not.toHaveBeenCalled();
  });

  it.each(['frame', 'window', 'method', 'window access', 'print access', 'focus', 'print'])(
    'opens the PDF when %s is unavailable',
    (failure) => {
      const open = vi.fn();
      vi.stubGlobal('window', { open });
      const denied = () => { throw new Error('PDF viewer is inaccessible'); };
      const viewer = { focus: vi.fn(), print: vi.fn() };
      const frame: Parameters<typeof printPdf>[0] = { contentWindow: viewer };
      if (failure === 'window') Object.defineProperty(frame, 'contentWindow', { value: null });
      if (failure === 'method') Object.defineProperty(viewer, 'print', { value: undefined });
      if (failure === 'window access') Object.defineProperty(frame, 'contentWindow', { get: denied });
      if (failure === 'print access') Object.defineProperty(viewer, 'print', { get: denied });
      if (failure === 'focus') viewer.focus.mockImplementation(denied);
      if (failure === 'print') viewer.print.mockImplementation(denied);

      expect(() => printPdf(failure === 'frame' ? null : frame, url)).not.toThrow();
      expect(open).toHaveBeenCalledExactlyOnceWith(url, '_blank', 'noopener,noreferrer');
    },
  );

  it('does nothing until a PDF has been fetched', () => {
    const open = vi.fn();
    vi.stubGlobal('window', { open });
    const viewer = { focus: vi.fn(), print: vi.fn() };
    printPdf({ contentWindow: viewer }, null);
    expect(viewer.focus).not.toHaveBeenCalled();
    expect(viewer.print).not.toHaveBeenCalled();
    expect(open).not.toHaveBeenCalled();
  });
});
