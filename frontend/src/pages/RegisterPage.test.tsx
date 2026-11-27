import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

const config = vi.hoisted(() => ({
  value: { password_signup_enabled: true, password_reset_enabled: true, providers: [{ id: 'google', name: 'Google' }], isLoading: false },
}));
vi.mock('../hooks/useAuthConfig', () => ({ useAuthConfig: () => config.value }));

import RegisterPage from './RegisterPage';

function render() {
  return renderToStaticMarkup(
    <MemoryRouter initialEntries={['/register']}>
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
});
