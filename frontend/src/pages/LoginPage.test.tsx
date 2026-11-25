import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

vi.mock('../context/AuthContext', () => ({ useAuth: () => ({ login: vi.fn() }) }));
vi.mock('../hooks/useAuthConfig', () => ({
  useAuthConfig: () => ({ password_signup_enabled: true, password_reset_enabled: true, providers: [] }),
}));

import LoginPage from './LoginPage';

function render(path = '/login') {
  return renderToStaticMarkup(<MemoryRouter initialEntries={[path]}><LoginPage /></MemoryRouter>);
}

describe('LoginPage confirmation guidance', () => {
  it('explains confirmation and password setup alongside the resend action', () => {
    const html = render('/login?error=email_not_verified');
    expect(html).toContain('Just signed up?');
    expect(html).toContain('confirm your address and choose your password');
    expect(html).toContain('Resend verification email');
    expect(html).toContain('type="button"');
  });

  it('keeps the initial form free of failure guidance', () => {
    const html = render();
    expect(html).not.toContain('Just signed up?');
    expect(html).not.toContain('Resend verification email');
    expect(html).toContain('Forgot password?');
    expect(html).toContain('Create account');
  });
});
