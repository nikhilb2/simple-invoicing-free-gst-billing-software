import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import CheckEmailNotice from './CheckEmailNotice';

function render(email: string) {
  return renderToStaticMarkup(
    <MemoryRouter>
      <CheckEmailNotice email={email} onChangeAddress={vi.fn()} onResend={vi.fn()} toasts={null} />
    </MemoryRouter>,
  );
}

describe('CheckEmailNotice', () => {
  it('shows the address on its own line with a way to change it', () => {
    const html = render('dev-signup-check@gmaui.com');
    expect(html).toContain('<p class="sent-address">dev-signup-check@gmaui.com</p>');
    expect(html).toContain('Wrong address? Change it');
    expect(html).toContain('type="button"');
  });

  it('keeps the confirm, resend and sign-in guidance', () => {
    const html = render('a@example.com');
    expect(html).toContain('confirm your address and choose your password');
    expect(html).toContain('If you already have an account with');
    expect(html).toContain('Resend verification email');
    expect(html).toContain('Go to sign in');
  });
});
