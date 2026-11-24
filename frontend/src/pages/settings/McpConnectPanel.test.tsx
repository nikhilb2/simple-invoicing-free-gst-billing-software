import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import McpConnectPanel, { MCP_GUIDE_URL, MCP_VIDEO_URL } from './McpConnectPanel';

describe('McpConnectPanel', () => {
  it('shows the URL to paste, a copy button and the guide', () => {
    const html = renderToStaticMarkup(<McpConnectPanel mcpUrl="https://app.gstbill.in/mcp" />);
    expect(html).toContain('https://app.gstbill.in/mcp');
    expect(html).toContain('Copy MCP server URL');
    expect(html).toContain(`href="${MCP_GUIDE_URL}"`);
    expect(html).toContain('target="_blank"');
  });

  it('links the ChatGPT video next to the guide when MCP is on', () => {
    const html = renderToStaticMarkup(<McpConnectPanel mcpUrl="https://app.gstbill.in/mcp" />);
    expect(html).toContain(`href="${MCP_VIDEO_URL}"`);
    expect(html).toContain('Watch: connect ChatGPT');
    expect(MCP_VIDEO_URL).toBe('https://youtu.be/5uzLToAxPwo');
  });

  it('leaves the video out when MCP is switched off', () => {
    const html = renderToStaticMarkup(<McpConnectPanel mcpUrl={null} />);
    expect(html).not.toContain(MCP_VIDEO_URL);
  });

  it('says MCP is off, and still links the guide, when the server has no URL', () => {
    const html = renderToStaticMarkup(<McpConnectPanel mcpUrl={null} />);
    expect(html).toContain('switched off');
    expect(html).not.toContain('Copy MCP server URL');
    expect(html).toContain(`href="${MCP_GUIDE_URL}"`);
  });

  it('shows neither while the config is loading', () => {
    const html = renderToStaticMarkup(<McpConnectPanel mcpUrl={undefined} isLoading />);
    expect(html).not.toContain('switched off');
    expect(html).not.toContain('Copy MCP server URL');
  });

  it('points at the AI assistants page of the guide', () => {
    expect(MCP_GUIDE_URL).toBe('https://guide.gstbill.in/integrations/ai-assistants');
  });
});
