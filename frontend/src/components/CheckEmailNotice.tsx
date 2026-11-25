import { Link } from 'react-router-dom';
import type { ReactNode } from 'react';

type Props = {
  email: string;
  onChangeAddress: () => void;
  onResend: () => void;
  toasts: ReactNode;
};

// Shown after email sign-up. The address gets its own line so a typo is easy to
// spot, with a way back to the form (name and email still filled in).
export default function CheckEmailNotice({ email, onChangeAddress, onResend, toasts }: Props) {
  return (
    <>
      <div>
        <p className="eyebrow">Almost there</p>
        <h2 className="page-title">Check your email</h2>
        <p className="section-copy">We have sent an email to:</p>
        <p className="sent-address">{email}</p>
        <button type="button" className="link-button link-button--tap" onClick={onChangeAddress}>
          Wrong address? Change it
        </button>
        <p className="section-copy">
          Open its link to confirm your address and choose your password. If you already have an account with
          this address, the email tells you how to sign in instead.
        </p>
      </div>
      {toasts}
      <button type="button" className="button button--ghost" onClick={onResend}>
        Resend verification email
      </button>
      {/* People who signed up before, often with Google, land here and wait for a
          link; the way back in has to be a button, not a footnote. */}
      <div className="stack" style={{ gap: '8px' }}>
        <p className="muted-text" style={{ margin: 0 }}>
          Already confirmed your email and chosen a password, or signed up with Google?
        </p>
        <Link to="/login" className="button button--secondary">Go to sign in</Link>
        <Link to="/forgot-password" style={{ textDecoration: 'underline' }}>Forgot your password?</Link>
      </div>
    </>
  );
}
