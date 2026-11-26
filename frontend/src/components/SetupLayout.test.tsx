import { renderToString } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import { GUIDE_URL, SetupFrame } from './SetupLayout';

// The frame itself needs neither; the wrapper that signs out does.
vi.mock('../context/AuthContext', () => ({ useAuth: () => ({ logout: () => undefined }) }));
vi.mock('./UpdateAvailableToast', () => ({ default: () => null }));

describe('SetupFrame (the frame around "Add your business")', () => {
  const html = renderToString(
    <SetupFrame onSignOut={() => undefined}>
      <p>page</p>
    </SetupFrame>,
  );

  it('has the brand on the left and Sign out and help on the right', () => {
    const brand = html.indexOf('Simple Invoicing');
    expect(brand).toBeGreaterThan(-1);
    expect(html).toContain('Stock &amp; billing');
    expect(html.indexOf('Sign out')).toBeGreaterThan(brand);
    expect(html).toContain('<button type="button" class="link-button link-button--tap">Sign out</button>');
    expect(html).toContain(`href="${GUIDE_URL}"`);
    expect(html).toContain('aria-label="Open the user guide"');
    expect(html.indexOf('Open the user guide')).toBeGreaterThan(html.indexOf('Sign out'));
  });

  it('renders the page inside the centred frame', () => {
    expect(html).toContain('<main class="page-frame setup-shell__main"><p>page</p></main>');
  });

  it('leaves out the app around it', () => {
    for (const gone of [
      'sidebar',
      'Open navigation',
      'settings-nav',
      'All settings',
      'github',
      'Request a feature',
      'theme-toggle',
      'for shortcuts',
      'Logout',
    ]) {
      expect(html, gone).not.toContain(gone);
    }
  });
});
