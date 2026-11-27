import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

vi.mock('../context/AuthContext', () => ({ useAuth: () => ({ login: vi.fn() }) }));
vi.mock('../hooks/useAuthConfig', () => ({
  useAuthConfig: () => ({ password_signup_enabled: true, password_reset_enabled: true, providers: [] }),
}));

import LoginPage from './LoginPage';

function render(path = '/login', state?: unknown) {
  return renderToStaticMarkup(
    <MemoryRouter initialEntries={[{ pathname: path.split('?')[0], search: path.includes('?') ? `?${path.split('?')[1]}` : '', state }]}>
      <LoginPage />
    </MemoryRouter>,
  );
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

describe('LoginPage after a session ended', () => {
  const reasonPath = '/login?next=%2Finvoices-view&reason=session_expired';

  it('says the visitor was signed out, in the page header', () => {
    const html = render(reasonPath);
    expect(html).toContain('Session ended');
    expect(html).toContain('Sign in again');
    expect(html).toContain('You were signed out. Sign in again to continue.');
    expect(html).not.toContain('Welcome back');
  });

  it('keeps the normal header with no reason or an unknown one', () => {
    for (const path of ['/login', '/login?reason=other', '/login?reason=oauth_failed']) {
      const html = render(path);
      expect(html).toContain('Welcome back');
      expect(html).not.toContain('Session ended');
    }
  });

  it('fills the email from router state and puts focus in Password', () => {
    const html = render(reasonPath, { email: 'owner@example.com' });
    expect(html).toContain('value="owner@example.com"');
    expect(html).toMatch(/<input[^>]*id="password"[^>]*autoFocus|<input[^>]*autoFocus[^>]*id="password"/i);
  });

  it('leaves the email empty and focus alone when no email is known', () => {
    const html = render(reasonPath);
    expect(html).not.toContain('owner@example.com');
    expect(html).not.toMatch(/autoFocus/i);
  });

  it('does not take the email from the URL', () => {
    const html = render('/login?reason=session_expired&email=owner@example.com');
    expect(html).not.toContain('value="owner@example.com"');
  });
});

describe('LoginPage sign-up nudge', () => {
  it('invites a visitor to create an account when sign-up is on', () => {
    const html = render().replace(/<!-- -->/g, '');
    expect(html).toContain('New here?');
    expect(html).toContain('href="/register"');
    expect(html).toContain('Create a free account');
  });
});
