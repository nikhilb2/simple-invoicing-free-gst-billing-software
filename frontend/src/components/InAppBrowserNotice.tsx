import { useEffect, useRef, useState } from 'react';
import { copyTextToClipboard } from '../utils/clipboard';
import {
  inAppBrowserApp,
  inAppBrowserPlatform,
  isInAppBrowser,
} from '../utils/inAppBrowser';

export const LINK_COPIED_MS = 3000;

type Props = {
  /** "sign up" on /register, "sign in" on /login. */
  emailAction: 'sign up' | 'sign in';
  /** Injected by tests; defaults to the browser's own. */
  userAgent?: string;
  href?: string;
};

/** Copies the link, then reports success and schedules the label to revert. */
export async function copyLink(
  href: string,
  copy: (text: string) => Promise<boolean>,
  onCopied: () => void,
): Promise<boolean> {
  const ok = await copy(href);
  if (ok) onCopied();
  return ok;
}

/**
 * Google refuses sign-in inside Instagram/Facebook's embedded browsers, and the
 * button then just reloads the page. Says so above the Google button.
 */
export default function InAppBrowserNotice({
  emailAction,
  userAgent = typeof navigator === 'undefined' ? '' : navigator.userAgent,
  href,
}: Props) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout>>();
  useEffect(() => () => clearTimeout(timer.current), []);

  if (!isInAppBrowser(userAgent)) {
    return null;
  }

  const app = inAppBrowserApp(userAgent);
  const platform = inAppBrowserPlatform(userAgent);
  const where = app === 'other' ? 'this app' : app;
  const menu =
    platform === 'ios'
      ? 'Tap ••• at the top right and choose “Open in external browser”'
      : 'Tap ⋮ at the top right and choose “Open in Chrome”';

  const onCopy = () =>
    copyLink(href ?? window.location.href, copyTextToClipboard, () => {
      setCopied(true);
      clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopied(false), LINK_COPIED_MS);
    });

  return (
    <div className="marketplace-note marketplace-note--emphasis in-app-notice" data-testid="in-app-browser-notice">
      <strong className="in-app-notice__title">Google sign-in doesn’t work inside {where}.</strong>
      <span>{menu}, or {emailAction} with your email below.</span>
      <button type="button" className="button button--ghost button--small in-app-notice__copy" onClick={onCopy}>
        <span aria-live="polite">{copied ? 'Link copied' : 'Copy link'}</span>
      </button>
    </div>
  );
}
