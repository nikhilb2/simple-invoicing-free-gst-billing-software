import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

const config = vi.hoisted(() => ({
  value: { password_signup_enabled: true, password_reset_enabled: true, providers: [{ id: 'google', name: 'Google' }], isLoading: false },
}));
vi.mock('../hooks/useAuthConfig', () => ({ useAuthConfig: () => config.value }));

import RegisterPage from './RegisterPage';

function render(entry = '/register') {
  return renderToStaticMarkup(
    <MemoryRouter initialEntries={[entry]}>
      <RegisterPage />
    </MemoryRouter>,
  ).replace(/<!-- -->/g, '');
}

describe('RegisterPage', () => {
  it('offers Sign in once, under the page text, and says Continue with Google', () => {
    const html = render();
    expect(html.match(/Already have an account\?/g)).toHaveLength(1);
    expect(html.indexOf('Already have an account?')).toBeLessThan(html.indexOf('Continue with Google'));
    expect(html).toContain('Continue with Google');
    expect(html).not.toContain('Sign up with Google');
    expect(html).toContain('Works for new and existing Google accounts.');
    expect(html).toContain('or sign up with your email');
  });

  it('has no Google button or hint when Google is not configured', () => {
    config.value = { ...config.value, providers: [] };
    const html = render();
    expect(html).not.toContain('Google');
    expect(html).toContain('Already have an account?');
  });

  it('carries next through the Sign in link and the Google button', () => {
    const html = render('/register?next=%2Finvoices%3Futm_source%3Dchatgpt.com');
    // A normal link: Sign in never redirects back to Create account, so there
    // is nothing to bounce, and signing in lands on the deep link.
    expect(html).toContain('href="/login?next=%2Finvoices%3Futm_source%3Dchatgpt.com"');
    expect(html).toContain('next=%2Finvoices%3Futm_source%3Dchatgpt.com');
  });

  it('drops next from both when the page was opened directly', () => {
    const html = render();
    expect(html).toContain('href="/login"');
    expect(html).not.toContain('next=%2Finvoices');
  });

  it('drops an unsafe next from both', () => {
    const html = render('/register?next=%2F%2Fevil.com');
    expect(html).toContain('href="/login"');
    expect(html).not.toContain('evil.com');
  });
});
