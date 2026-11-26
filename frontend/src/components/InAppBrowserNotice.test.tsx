import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import InAppBrowserNotice, { copyLink } from './InAppBrowserNotice';
import OAuthButtons from './OAuthButtons';

const IG_ANDROID =
  'Mozilla/5.0 (Linux; Android 14; Pixel 8 Build/UQ1A.240205.004; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/131.0.6778.135 Mobile Safari/537.36 Instagram 358.0.0.47.97 Android';
const IG_IOS =
  'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/21F79 Instagram 358.0.0.30.89 (iPhone15,2; iOS 17_5; en_IN; en; scale=3.00; 1170x2532; 612345678)';
const FB_ANDROID =
  'Mozilla/5.0 (Linux; Android 13; SM-S918B; wv) AppleWebKit/537.36 Chrome/130.0 Mobile Safari/537.36 [FB_IAB/FB4A;FBAV/480.0.0.40.108;]';
const LINE_ANDROID = 'Mozilla/5.0 (Linux; Android 13; SM-S918B) Chrome/130.0 Mobile Safari/537.36 Line/14.8.0';
const CHROME_ANDROID =
  'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.6778.135 Mobile Safari/537.36';
const SAFARI_IOS =
  'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1';
const DESKTOP =
  'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36';

const render = (userAgent: string, emailAction: 'sign up' | 'sign in' = 'sign up') =>
  renderToStaticMarkup(<InAppBrowserNotice emailAction={emailAction} userAgent={userAgent} />).replace(/<!-- -->/g, '');

describe('InAppBrowserNotice', () => {
  it('names Instagram and gives the Android menu wording', () => {
    const html = render(IG_ANDROID);
    expect(html).toContain('Google sign-in doesn’t work inside Instagram.');
    expect(html).toContain('Tap ⋮ at the top right and choose “Open in Chrome”, or sign up with your email below.');
    expect(html).toContain('marketplace-note marketplace-note--emphasis');
    expect(html).toContain('button button--ghost button--small');
    expect(html).toContain('Copy link');
  });

  it('uses the iPhone wording on iOS', () => {
    const html = render(IG_IOS);
    expect(html).toContain('inside Instagram.');
    expect(html).toContain('Tap ••• at the top right and choose “Open in external browser”, or sign up with your email below.');
  });

  it('names Facebook, and "this app" for anything else', () => {
    expect(render(FB_ANDROID)).toContain('inside Facebook.');
    expect(render(LINE_ANDROID)).toContain('inside this app.');
  });

  it('says "sign in" on the login page', () => {
    expect(render(IG_ANDROID, 'sign in')).toContain('or sign in with your email below.');
  });

  it.each([
    ['Chrome on Android', CHROME_ANDROID],
    ['Safari on iPhone', SAFARI_IOS],
    ['desktop Chrome', DESKTOP],
  ])('renders nothing in %s', (_n, ua) => {
    expect(render(ua)).toBe('');
  });
});

describe('InAppBrowserNotice in the Google button block', () => {
  const google = { id: 'google', name: 'Google' };
  const html = (ua: string) =>
    renderToStaticMarkup(<OAuthButtons providers={[google]} next="/" label="Sign up with" emailAction="sign up" userAgent={ua} />);

  it('sits above the Google button, which stays', () => {
    const out = html(IG_ANDROID);
    expect(out.indexOf('in-app-browser-notice')).toBeGreaterThan(-1);
    expect(out.indexOf('in-app-browser-notice')).toBeLessThan(out.indexOf('oauth-google'));
    expect(out).toContain('data-testid="oauth-google"');
  });

  it('is absent in a normal browser', () => {
    expect(html(CHROME_ANDROID)).not.toContain('in-app-browser-notice');
  });

  it('is absent when no provider is enabled', () => {
    expect(renderToStaticMarkup(<OAuthButtons providers={[]} next="/" userAgent={IG_ANDROID} />)).toBe('');
  });
});

describe('copyLink', () => {
  const href = 'https://gstbill.in/register?utm_source=instagram&utm_medium=bio';

  it('copies the full URL, query string included, then reports success', async () => {
    const copy = vi.fn().mockResolvedValue(true);
    const onCopied = vi.fn();
    expect(await copyLink(href, copy, onCopied)).toBe(true);
    expect(copy).toHaveBeenCalledWith(href);
    expect(onCopied).toHaveBeenCalledOnce();
  });

  it('does not claim success when the copy fails', async () => {
    const onCopied = vi.fn();
    expect(await copyLink(href, vi.fn().mockResolvedValue(false), onCopied)).toBe(false);
    expect(onCopied).not.toHaveBeenCalled();
  });
});
