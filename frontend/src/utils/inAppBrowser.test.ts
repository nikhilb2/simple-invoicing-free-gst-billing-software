import { describe, expect, it } from 'vitest';
import { inAppBrowserApp, inAppBrowserPlatform, isInAppBrowser } from './inAppBrowser';

const INSTAGRAM_ANDROID =
  'Mozilla/5.0 (Linux; Android 14; Pixel 8 Build/UQ1A.240205.004; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/131.0.6778.135 Mobile Safari/537.36 Instagram 358.0.0.47.97 Android';
const INSTAGRAM_IOS =
  'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/21F79 Instagram 358.0.0.30.89 (iPhone15,2; iOS 17_5; en_IN; en; scale=3.00; 1170x2532; 612345678)';
const FACEBOOK_ANDROID =
  'Mozilla/5.0 (Linux; Android 13; SM-S918B Build/TP1A.220624.014; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/130.0.6723.102 Mobile Safari/537.36 [FB_IAB/FB4A;FBAV/480.0.0.40.108;]';
const FACEBOOK_IOS =
  'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/21F79 [FBAN/FBIOS;FBAV/470.0.0.40.108;FBBV/600000;FBDV/iPhone15,2;FBMD/iPhone;FBSN/iOS;FBSV/17.5;FBLC/en_US;FBOP/5]';
const LINE_IOS =
  'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/21F79 Safari Line/14.8.0';
const CHROME_ANDROID =
  'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.6778.135 Mobile Safari/537.36';
const SAFARI_IOS =
  'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1';
const DESKTOP_CHROME =
  'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36';

describe('isInAppBrowser', () => {
  it.each([
    ['Instagram on Android', INSTAGRAM_ANDROID],
    ['Instagram on iPhone', INSTAGRAM_IOS],
    ['Facebook on Android', FACEBOOK_ANDROID],
    ['Facebook on iPhone', FACEBOOK_IOS],
    ['LINE', LINE_IOS],
    ['a bare Android WebView', 'Mozilla/5.0 (Linux; Android 14; Pixel 8; wv) AppleWebKit/537.36 Chrome/131.0 Mobile Safari/537.36'],
  ])('detects %s', (_name, ua) => {
    expect(isInAppBrowser(ua)).toBe(true);
  });

  it.each([
    ['Chrome on Android', CHROME_ANDROID],
    ['Safari on iPhone', SAFARI_IOS],
    ['desktop Chrome', DESKTOP_CHROME],
    ['an empty user agent', ''],
  ])('does not flag %s', (_name, ua) => {
    expect(isInAppBrowser(ua)).toBe(false);
  });
});

describe('inAppBrowserApp', () => {
  it('names Instagram, Facebook, or other', () => {
    expect(inAppBrowserApp(INSTAGRAM_ANDROID)).toBe('Instagram');
    expect(inAppBrowserApp(INSTAGRAM_IOS)).toBe('Instagram');
    expect(inAppBrowserApp(FACEBOOK_ANDROID)).toBe('Facebook');
    expect(inAppBrowserApp(FACEBOOK_IOS)).toBe('Facebook');
    expect(inAppBrowserApp(LINE_IOS)).toBe('other');
  });
});

describe('inAppBrowserPlatform', () => {
  it('tells Android from iPhone', () => {
    expect(inAppBrowserPlatform(INSTAGRAM_ANDROID)).toBe('android');
    expect(inAppBrowserPlatform(INSTAGRAM_IOS)).toBe('ios');
    expect(inAppBrowserPlatform(DESKTOP_CHROME)).toBe('other');
  });
});
