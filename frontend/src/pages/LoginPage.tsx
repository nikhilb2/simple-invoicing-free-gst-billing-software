import { FormEvent, useState } from 'react';
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { resendVerification } from '../api/auth';
import { useAuth } from '../context/AuthContext';
import { useAuthConfig } from '../hooks/useAuthConfig';
import { authErrorMessage, loginErrorMessage, loginReasonNotice } from '../utils/authFlow';
import { sanitizeNextPath } from '../utils/nextPath';
import AuthLayout from '../components/AuthLayout';
import OAuthButtons from '../components/OAuthButtons';
import StatusToasts from '../components/StatusToasts';
import PasswordInput from '../components/PasswordInput';

export default function LoginPage() {
  // The email of the session that just ended, handed over in router state by
  // api/client.ts -- never in the URL.
  const location = useLocation();
  const endedEmail = (location.state as { email?: unknown } | null)?.email;
  const [email, setEmail] = useState(typeof endedEmail === 'string' ? endedEmail : '');
  const [password, setPassword] = useState('');
  const [searchParams] = useSearchParams();
  // The OAuth callback redirects here with ?error=<code>.
  const [error, setError] = useState(() => loginErrorMessage(searchParams.get('error')));
  const [success, setSuccess] = useState('');
  const [showVerificationHelp, setShowVerificationHelp] = useState(
    () => searchParams.get('error') === 'email_not_verified',
  );
  const [submitting, setSubmitting] = useState(false);
  const [resending, setResending] = useState(false);
  const { login } = useAuth();
  const navigate = useNavigate();
  const config = useAuthConfig();
  // Where Protected wanted to send them. Validated, never trusted — an
  // unchecked ?next= is an open redirect aimed at a user who has just typed
  // their password. See utils/nextPath.ts.
  const next = sanitizeNextPath(searchParams.get('next'));
  const notice = loginReasonNotice(searchParams.get('reason'));

  async function onSubmit(event: FormEvent) {
    event.preventDefault();

    try {
      setSubmitting(true);
      setError('');
      setSuccess('');
      setShowVerificationHelp(false);
      await login(email, password);
      navigate(next, { replace: true });
    } catch (err) {
      // A new account has no password until its email link is opened. The API
      // deliberately returns the same error as a wrong password, so offer
      // generic guidance without inferring whether this address has an account.
      setShowVerificationHelp(true);
      setError(authErrorMessage(err, 'Unable to sign in'));
    } finally {
      setSubmitting(false);
    }
  }

  async function onResend() {
    if (!email.trim()) {
      setError('Enter your email address above, then ask for the link again.');
      return;
    }
    try {
      setResending(true);
      setError('');
      const res = await resendVerification(email.trim());
      setSuccess(res.detail || 'If that account needs verifying, a new link is on its way.');
    } catch (err) {
      setError(authErrorMessage(err, 'Unable to resend the verification email'));
    } finally {
      setResending(false);
    }
  }

  return (
    <AuthLayout title="Login">
      <div>
        <p className="eyebrow">{notice?.eyebrow ?? 'Welcome back'}</p>
        <h2 className="page-title">{notice?.title ?? 'Sign in'}</h2>
        <p className="section-copy">
          {notice?.copy ?? 'Enter your email and password to see your invoices, stock and payments.'}
        </p>
        {config.password_signup_enabled || config.providers.length > 0 ? (
          <p className="section-copy">
            New here?{' '}
            <Link to="/register" style={{ fontWeight: 700, textDecoration: 'underline', color: 'var(--accent)' }}>Create a free account</Link>
          </p>
        ) : null}
      </div>

      <OAuthButtons providers={config.providers} next={next} />

      <form onSubmit={onSubmit} className="stack">
        <div className="field--full">
          <label htmlFor="email">Email</label>
          <input
            id="email"
            className="input"
            type="email"
            placeholder="you@example.com"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            autoComplete="email"
          />
        </div>

        <div className="field--full">
          <label htmlFor="password">Password</label>
          <PasswordInput
            id="password"
            className="input"
            placeholder="Enter password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="current-password"
            autoFocus={email !== ''}
          />
        </div>

        <StatusToasts error={error} success={success} onClearError={() => setError('')} onClearSuccess={() => setSuccess('')} />

        {showVerificationHelp ? (
          <div className="stack" style={{ gap: '8px' }}>
            <p className="muted-text" style={{ margin: 0 }}>
              Just signed up? Open the email we sent you to confirm your address and choose your password.
            </p>
            <button
              type="button"
              className="button button--ghost"
              onClick={() => void onResend()}
              disabled={resending}
            >
              {resending ? 'Sending...' : 'Resend verification email'}
            </button>
          </div>
        ) : null}

        <button className="button button--primary" disabled={submitting} title="Sign in" aria-label="Sign in">
          {submitting ? 'Signing in...' : 'Sign in'}
        </button>
      </form>

      {config.password_reset_enabled || config.password_signup_enabled ? (
        <p className="muted-text" style={{ margin: 0 }}>
          {config.password_reset_enabled ? <Link to="/forgot-password">Forgot password?</Link> : null}
          {config.password_reset_enabled && config.password_signup_enabled ? ' · ' : null}
          {config.password_signup_enabled ? <Link to="/register">Create account</Link> : null}
        </p>
      ) : null}
    </AuthLayout>
  );
}
