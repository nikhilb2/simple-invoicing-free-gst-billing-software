export type InAppBrowserApp = 'Instagram' | 'Facebook' | 'other';
export type InAppBrowserPlatform = 'android' | 'ios' | 'other';

/**
 * Whether the page runs inside another app's embedded browser. Google refuses
 * OAuth in those, so tapping "Sign up with Google" there just reloads the page.
 * Matches Instagram, Facebook (FBAN/FBAV/FB_IAB), LINE, and any Android WebView.
 */
export function isInAppBrowser(userAgent: string): boolean {
  return /Instagram|FBAN|FBAV|FB_IAB|Line\/|; wv\)/.test(userAgent);
}

/** Which app the in-app browser belongs to; "other" for anything not named. */
export function inAppBrowserApp(userAgent: string): InAppBrowserApp {
  if (/Instagram/.test(userAgent)) return 'Instagram';
  if (/FBAN|FBAV|FB_IAB/.test(userAgent)) return 'Facebook';
  return 'other';
}

export function inAppBrowserPlatform(userAgent: string): InAppBrowserPlatform {
  if (/Android/.test(userAgent)) return 'android';
  if (/iPhone|iPad|iPod/.test(userAgent)) return 'ios';
  return 'other';
}
