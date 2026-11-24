import { useState } from 'react';
import { BookOpen, Check, Copy, CirclePlay } from 'lucide-react';
import { copyTextToClipboard } from '../../utils/clipboard';

export const MCP_GUIDE_URL = 'https://guide.gstbill.in/integrations/ai-assistants';
/** 1.5-minute walkthrough (Hinglish, subtitled): connecting ChatGPT, then using it on real invoices. */
export const MCP_VIDEO_URL = 'https://youtu.be/5uzLToAxPwo';

type McpConnectPanelProps = {
  /** From /auth/config: the exact address the OAuth metadata names, or null when MCP is off. */
  mcpUrl: string | null | undefined;
  isLoading?: boolean;
};

/**
 * Where a new connection starts: the address to paste into Claude, ChatGPT or
 * another MCP client, and the guide that walks through it. The URL comes from the
 * server rather than window.location, because a self-hosted API can live on a
 * different host from the app, and a client that is given anything other than the
 * advertised resource rejects the token it gets back.
 */
export default function McpConnectPanel({ mcpUrl, isLoading = false }: McpConnectPanelProps) {
  const [copied, setCopied] = useState(false);

  async function copyUrl() {
    if (mcpUrl && (await copyTextToClipboard(mcpUrl))) {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  }

  const guideLink = (
    <a className="button button--secondary" href={MCP_GUIDE_URL} target="_blank" rel="noopener noreferrer">
      <BookOpen size={15} aria-hidden="true" /> How to connect
    </a>
  );

  return (
    <section className="panel stack" aria-labelledby="mcp-connect-title" style={{ gap: '12px' }}>
      <div>
        <p className="eyebrow">Connect an AI assistant</p>
        <h2 id="mcp-connect-title" className="nav-panel__title">MCP server URL</h2>
      </div>

      {isLoading ? (
        <p style={{ opacity: 0.5 }}>Loading…</p>
      ) : mcpUrl ? (
        <>
          <p className="section-copy">
            Add a custom connector in Claude, ChatGPT or another MCP client with this URL, then sign in and approve
            access for one company.
          </p>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              background: 'var(--color-surface-2)',
              border: '1px solid var(--color-border)',
              borderRadius: '8px',
              padding: '8px 8px 8px 12px',
            }}
          >
            <code id="mcp-url" style={{ flex: 1, minWidth: 0, fontSize: '0.85rem', wordBreak: 'break-all' }}>
              {mcpUrl}
            </code>
            <button
              type="button"
              className="button button--ghost"
              style={{ flexShrink: 0, padding: '4px 10px' }}
              onClick={() => void copyUrl()}
              aria-label="Copy MCP server URL"
              title="Copy to clipboard"
            >
              {copied ? <Check size={14} aria-hidden="true" /> : <Copy size={14} aria-hidden="true" />}
              {copied ? ' Copied' : ' Copy'}
            </button>
          </div>
          <div className="button-row">
            {guideLink}
            <a className="button button--secondary" href={MCP_VIDEO_URL} target="_blank" rel="noopener noreferrer">
              <CirclePlay size={15} aria-hidden="true" /> Watch: connect ChatGPT
            </a>
          </div>
        </>
      ) : (
        <>
          <p className="section-copy">
            Connecting AI assistants is switched off on this server. The guide explains how
            to turn it on for your own copy.
          </p>
          <div className="button-row">{guideLink}</div>
        </>
      )}
    </section>
  );
}
