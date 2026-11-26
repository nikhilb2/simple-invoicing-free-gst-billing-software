import { useEffect } from 'react';
import { CircleHelp } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import BrandMark from './BrandMark';
import UpdateAvailableToast from './UpdateAvailableToast';

export const GUIDE_URL = 'https://guide.gstbill.in';

/**
 * The frame around "Add your business" while the user has no company (#963).
 *
 * Only the brand, "Sign out" and help. No sidebar or hamburger, no settings
 * sub-navigation, GitHub star, "Request a feature", theme toggle or shortcuts
 * hint: new users on phones spent their time in those (one for 23 minutes) and
 * never typed in the one field that gets them in. Hiding beats locking: the
 * sidebar already greyed its rows out, and people still went round in circles.
 * The WhatsApp bubble is outside this frame and stays where it always is.
 */
export function SetupFrame({ onSignOut, children }: { onSignOut: () => void; children: React.ReactNode }) {
  return (
    <div className="setup-shell">
      <header className="page-header setup-header">
        <div className="setup-header__brand">
          <BrandMark size={28} />
          <div>
            <span className="setup-header__name">Simple Invoicing</span>
            <span className="setup-header__tagline">Stock &amp; billing</span>
          </div>
        </div>
        <div className="setup-header__actions">
          <button type="button" className="link-button link-button--tap" onClick={onSignOut}>
            Sign out
          </button>
          <a
            className="button button--ghost button--small setup-header__help"
            href={GUIDE_URL}
            target="_blank"
            rel="noopener noreferrer"
            aria-label="Open the user guide"
            title="Open the user guide"
          >
            <CircleHelp size={16} aria-hidden="true" />
          </a>
        </div>
      </header>
      <main className="page-frame setup-shell__main">{children}</main>
    </div>
  );
}

export default function SetupLayout({ children }: { children: React.ReactNode }) {
  const { logout } = useAuth();

  useEffect(() => {
    document.title = 'Add your business | Simple Invoicing';
  }, []);

  return (
    <>
      <SetupFrame onSignOut={() => logout()}>{children}</SetupFrame>
      <UpdateAvailableToast />
    </>
  );
}
