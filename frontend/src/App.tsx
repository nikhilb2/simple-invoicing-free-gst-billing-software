import { Suspense, lazy, useEffect, useState } from 'react';
import { Navigate, Route, Routes, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { MotionConfig } from 'framer-motion';
import { useAuthStore } from './store/useAuthStore';
import { AuthProvider, useAuth } from './context/AuthContext';
import { FYProvider } from './context/FYContext';
import { ShortcutsProvider } from './context/ShortcutsContext';
import axios from 'axios';
import api, { setSessionEndedHandler } from './api/client';
import type { CompanyProfile } from './types/api';
import { COMPANY_SETUP_PATH, isCompanyConfigured, isCompanySetupRequired, setupRouteAction, type SetupRouteMode } from './utils/companySetup';
import { hasSignedInBefore, sanitizeNextPath, signedOutLandingPath } from './utils/nextPath';
import { useAuthConfig } from './hooks/useAuthConfig';
import LoginPage from './pages/LoginPage';
import RegisterPage from './pages/RegisterPage';
import VerifyEmailPage from './pages/VerifyEmailPage';
import ForgotPasswordPage from './pages/ForgotPasswordPage';
import ResetPasswordPage from './pages/ResetPasswordPage';
import OAuthCallbackPage from './pages/OAuthCallbackPage';
import DashboardPage from './pages/DashboardPage';
import CataloguePage from './pages/CataloguePage';
import ProduceItemsPage from './pages/ProduceItemsPage';
import InvoicesPage from './pages/InvoicesPage';
import InvoiceDuesPage from './pages/InvoiceDuesPage';
import InvoicesAdvancedView from './pages/InvoicesAdvancedView';
import CreditNotesPage from './pages/CreditNotesPage';
import QuotationsPage from './pages/QuotationsPage';
import DeliveryChallansPage from './pages/DeliveryChallansPage';
import DeliveryChallanFormPage from './pages/DeliveryChallanFormPage';
import LedgersPage from './pages/LedgersPage';
import LedgerCreatePage from './pages/LedgerCreatePage';
import LedgerViewPage from './pages/LedgerViewPage';
import DayBookPage from './pages/DayBookPage';
import TaxLedgerPage from './pages/TaxLedgerPage';
import Gstr1FilingPage from './pages/Gstr1FilingPage';
import Gstr3bWorksheetPage from './pages/Gstr3bWorksheetPage';
import TdsReportPage from './pages/TdsReportPage';
import TcsCollectedPage from './pages/TcsCollectedPage';
import CashBankPage from './pages/CashBankPage';
import CashBankAccountsPage from './pages/CashBankAccountsPage';
import CompanyPage from './pages/CompanyPage';
import SmtpSettingsPage from './pages/SmtpSettingsPage';
import BackupsPage from './pages/BackupsPage';
import KeyboardShortcutsPage from './pages/KeyboardShortcutsPage';
import AppearancePage from './pages/AppearancePage';
import ChangePasswordPage from './pages/ChangePasswordPage';
import ApiKeysPage from './pages/ApiKeysPage';
import ConnectedAppsPage from './pages/settings/ConnectedAppsPage';
import OAuthConsentPage from './pages/oauth/OAuthConsentPage';
import EmailHistoryPage from './pages/EmailHistoryPage';
import MyListingsPage from './pages/marketplace/MyListingsPage';
import MarketplaceOrdersPage from './pages/marketplace/MarketplaceOrdersPage';
import MarketplaceSettingsPage from './pages/marketplace/MarketplaceSettingsPage';
import NotFoundPage from './pages/NotFoundPage';
import SettingsLayout from './pages/settings/SettingsLayout';
import SettingsOverviewPage from './pages/settings/SettingsOverviewPage';
import { LEGACY_REDIRECTS } from './config/navigation';
import Layout from './components/Layout';
import SetupLayout from './components/SetupLayout';
import WhatsAppSupportBubble from './components/WhatsAppSupportBubble';

// Lazily loaded: these are the only routes that pull in recharts (~100kb gz),
// and every other route here is imported eagerly — they shouldn't pay for it.
const AnalyticsPage = lazy(() => import('./pages/AnalyticsPage'));
const ProductPerformancePage = lazy(() => import('./pages/analytics/ProductPerformancePage'));

// Browse is the marketplace's heaviest page and the one an instance with no
// connection never opens, so it isn't in the main bundle either.
const MarketplaceBrowsePage = lazy(() => import('./pages/marketplace/MarketplaceBrowsePage'));

/**
 * Requires a session, and remembers where the visitor was going.
 *
 * The return path is not a nicety: an MCP client sends the user straight to
 * /oauth/consent?request_id=…, and before this carried `?next=` they signed in
 * and landed on the dashboard with the pending authorization request stranded.
 * `sanitizeNextPath` on the way back is what keeps that from being an open
 * redirect — see utils/nextPath.ts.
 */
function Protected({ children }: { children: React.ReactNode }) {
  const { isAuthenticated } = useAuth();

  return isAuthenticated ? children : <SignedOutRedirect />;
}

/**
 * Sends a signed-out visitor to Create account or Sign in (see signedOutLandingPath).
 *
 * Only a first-time visitor on `/` depends on the sign-up config, so only they
 * wait for it (rendering nothing, not the wrong page). If the config request
 * fails, useAuthConfig reports sign-up as off and they get Sign in.
 */
function SignedOutRedirect() {
  const location = useLocation();
  const sessionEnded = useAuthStore((s) => s.sessionEnded);
  const config = useAuthConfig();
  const [signedInBefore] = useState(hasSignedInBefore);

  const firstTimeHome = location.pathname === '/' && !sessionEnded && !signedInBefore;
  if (firstTimeHome && config.isLoading) {
    return null;
  }

  const to = signedOutLandingPath({
    pathname: location.pathname,
    search: location.search,
    sessionEnded: !!sessionEnded,
    signedInBefore,
    signupEnabled: config.password_signup_enabled || config.providers.length > 0,
  });
  // A session the server ended says so on the sign-in page, and hands over the email.
  return <Navigate to={to} state={sessionEnded ? { email: sessionEnded.email } : undefined} replace />;
}

function PublicOnly({ children }: { children: React.ReactNode }) {
  const { isAuthenticated } = useAuth();
  const [searchParams] = useSearchParams();

  if (isAuthenticated) {
    return <Navigate to={sanitizeNextPath(searchParams.get('next'))} replace />;
  }

  return children;
}

function AdminOnly({ platform = false, children }: { platform?: boolean; children: React.ReactNode }) {
  const { isAdmin, canManagePlatform, profileLoaded } = useAuth();

  // After a full page load the roles are empty until /auth/me answers. Judging
  // them then bounced a platform admin off /settings/email and /settings/backups
  // (pages that, unlike the others, do not wait on the company query first).
  if (!profileLoaded) {
    return <div className="empty-state">Loading…</div>;
  }

  if (platform ? !canManagePlatform : !isAdmin) {
    return <Navigate to="/" replace />;
  }

  return children;
}

function isCompanyRequiredError(error: unknown): boolean {
  return (
    axios.isAxiosError(error) &&
    error.response?.status === 409 &&
    error.response.data?.detail?.code === 'company_required'
  );
}

/** The active company, or the 409 that says there is none. Shared with the sidebar and the Get-started card. */
function useCompanySetupQuery() {
  return useQuery({
    queryKey: ['company-setup-required'],
    queryFn: async () => {
      const response = await api.get<CompanyProfile>('/company/');
      return response.data;
    },
    retry: false,
  });
}

function CompanyRequired({ children }: { children: React.ReactNode }) {
  const companyQuery = useCompanySetupQuery();

  if (companyQuery.isLoading) {
    return <div className="empty-state">Loading company profile...</div>;
  }

  // A 401 means the session ended: client.ts has already cleared it and is
  // sending the visitor to sign in. Neither the company-setup redirect nor
  // "Loading..." belongs here, and a 401 must not be mistaken for "no company".
  if (axios.isAxiosError(companyQuery.error) && companyQuery.error.response?.status === 401) {
    return null;
  }

  // A 409 company_required is the server saying this user has no company yet
  // (shared hosting never auto-creates one). Any other failure still lets the
  // user through, as before.
  if (isCompanyRequiredError(companyQuery.error)) {
    return <Navigate to="/settings/company?setup=required" replace />;
  }

  if (companyQuery.error) {
    return children;
  }

  if (!isCompanyConfigured(companyQuery.data)) {
    return <Navigate to="/settings/company?setup=required" replace />;
  }

  return children;
}

/**
 * A settings page that opens without a company, while there is none (#963).
 *
 * The company page is drawn in the setup-only frame rather than the app, and
 * the settings overview and Appearance send people to it: from them a new user
 * wandered off into Security, themes and the Company card that led back here.
 */
function CompanySetupAware({ mode, children }: { mode: SetupRouteMode; children: React.ReactNode }) {
  const companyQuery = useCompanySetupQuery();
  const setupRequired = isCompanySetupRequired(companyQuery.data, companyQuery.error, companyQuery.isLoading);
  // Once in the setup frame, stay in it until the route changes. Saving the first
  // company refreshes this query a moment before the page moves on to the
  // composer, and swapping to the full app in between would flash the sidebar.
  const [framed, setFramed] = useState(false);
  if (setupRequired && !framed) setFramed(true);

  if (companyQuery.isLoading) {
    return <div className="empty-state">Loading company profile...</div>;
  }

  const action = setupRouteAction(mode, setupRequired || framed);
  if (action === 'redirect') return <Navigate to={COMPANY_SETUP_PATH} replace />;
  if (action === 'setup-frame') return <SetupLayout>{children}</SetupLayout>;
  return (
    <Layout>
      <SettingsLayout>{children}</SettingsLayout>
    </Layout>
  );
}

/**
 * A settings page, framed by the settings sub-navigation.
 *
 * The guard combination is passed as props rather than nested by hand at each
 * call site keeps the route list readable. Platform settings do not need a
 * company; onboarding and personal preferences can also opt out of that guard.
 */
function SettingsRoute({
  admin = false,
  platform = false,
  requireCompany = !platform,
  setup,
  children,
}: {
  admin?: boolean;
  /** Uses the platform capability rather than the active company's admin role. */
  platform?: boolean;
  requireCompany?: boolean;
  /** For a page that opens without a company: what it does while there is none. */
  setup?: SetupRouteMode;
  children: React.ReactNode;
}) {
  let node = setup ? (
    <CompanySetupAware mode={setup}>{children}</CompanySetupAware>
  ) : (
    <Layout>
      <SettingsLayout>{children}</SettingsLayout>
    </Layout>
  );
  if (admin || platform) node = <AdminOnly platform={platform}>{node}</AdminOnly>;
  if (requireCompany) node = <CompanyRequired>{node}</CompanyRequired>;
  return <Protected>{node}</Protected>;
}

/**
 * A safety net for the public share page, which the backend serves at
 * /s/<token> — reachable only once this namespace's ingress routes that prefix.
 * If an ingress lags, is reverted, or is missed for one tenant, /s/<token>
 * falls through to this SPA, and the `*` catch-all below would answer a
 * customer's invoice link with a login screen. Bouncing to /api/s/<token>
 * instead lands them on the same page through a prefix the ingress has always
 * routed; the backend registers the public router under both.
 *
 * window.location, not <Navigate>: the target is a server-rendered page, not a
 * route this bundle knows how to draw.
 */
function PublicShareRedirect() {
  const { token } = useParams();
  // Anything that is not plainly a token gets the ordinary catch-all treatment
  // rather than a redirect to /api/s/undefined.
  const isToken = Boolean(token) && /^[A-Za-z0-9._~-]{1,200}$/.test(token as string);

  useEffect(() => {
    if (isToken) {
      window.location.replace(`/api/s/${token}`);
    }
  }, [isToken, token]);

  if (!isToken) {
    return <Navigate to="/" replace />;
  }

  return <p className="empty-state">Opening…</p>;
}

/** A moved route. Keeps the query string so ?setup=required survives the hop. */
function LegacyRedirect({ to }: { to: string }) {
  const { search, hash } = useLocation();
  return <Navigate to={`${to}${search}${hash}`} replace />;
}

/**
 * Lets api/client.ts, which lives outside the router, send a visitor whose
 * session ended to the sign-in page. Rendered before the routes so it is
 * registered before any page's first request can come back 401.
 */
function SessionEndedBridge() {
  const navigate = useNavigate();

  useEffect(() => {
    setSessionEndedHandler({
      getSession: () => {
        const { token, userEmail } = useAuthStore.getState();
        return token ? { email: userEmail } : null;
      },
      logout: (options) => useAuthStore.getState().logout(options),
      navigate: (path, state) => navigate(path, { replace: true, state }),
    });
    return () => setSessionEndedHandler(null);
  }, [navigate]);

  return null;
}

function AppRoutes() {
  return (
    <Routes>
      <Route
        path="/login"
        element={
          <PublicOnly>
            <LoginPage />
          </PublicOnly>
        }
      />
      <Route path="/register" element={<PublicOnly><RegisterPage /></PublicOnly>} />
      {/* Outside PublicOnly: these carry a one-time link or code, and a browser that
          still holds some session, even an expired one, must not be redirected away
          from it. */}
      <Route path="/verify-email" element={<VerifyEmailPage />} />
      <Route path="/forgot-password" element={<PublicOnly><ForgotPasswordPage /></PublicOnly>} />
      <Route path="/reset-password" element={<ResetPasswordPage />} />
      <Route path="/auth/callback" element={<OAuthCallbackPage />} />
      {/* Mid-flow from an external MCP client. Deliberately outside Layout and
          CompanyRequired: the visitor is answering one question, and a company
          setup redirect here would strand the pending authorization request. */}
      <Route path="/oauth/consent" element={<Protected><OAuthConsentPage /></Protected>} />
      <Route path="/" element={<Protected><CompanyRequired><Layout><DashboardPage /></Layout></CompanyRequired></Protected>} />
      <Route path="/catalogue" element={<Protected><CompanyRequired><Layout><CataloguePage /></Layout></CompanyRequired></Protected>} />
      {/* The three pages the catalogue replaces. /products-inventory is the
          target every MCP product and serial citation already points at, so the
          redirect has to carry ?product_id= / ?serial= across with it. */}
      <Route path="/products" element={<LegacyRedirect to="/catalogue" />} />
      <Route path="/inventory" element={<LegacyRedirect to="/catalogue" />} />
      <Route path="/products-inventory" element={<LegacyRedirect to="/catalogue" />} />
      <Route path="/produce-items" element={<Protected><CompanyRequired><Layout><ProduceItemsPage /></Layout></CompanyRequired></Protected>} />
      <Route path="/ledgers" element={<Protected><CompanyRequired><Layout><LedgersPage /></Layout></CompanyRequired></Protected>} />
      <Route path="/ledgers/new" element={<Protected><CompanyRequired><Layout><LedgerCreatePage /></Layout></CompanyRequired></Protected>} />
      <Route path="/ledgers/:id" element={<Protected><CompanyRequired><Layout><LedgerViewPage /></Layout></CompanyRequired></Protected>} />
      <Route path="/ledgers/:id/edit" element={<Protected><CompanyRequired><Layout><LedgerCreatePage /></Layout></CompanyRequired></Protected>} />
      <Route path="/analytics" element={<Protected><CompanyRequired><Layout><Suspense fallback={<div className="empty-state">Loading analytics…</div>}><AnalyticsPage /></Suspense></Layout></CompanyRequired></Protected>} />
      <Route path="/analytics/products/:productId" element={<Protected><CompanyRequired><Layout><Suspense fallback={<div className="empty-state">Loading analytics…</div>}><ProductPerformancePage /></Suspense></Layout></CompanyRequired></Protected>} />
      <Route path="/day-book" element={<Protected><CompanyRequired><Layout><DayBookPage /></Layout></CompanyRequired></Protected>} />
      <Route path="/tax-ledger" element={<Protected><CompanyRequired><Layout><TaxLedgerPage /></Layout></CompanyRequired></Protected>} />
      <Route path="/reports/tcs-collected" element={<Protected><CompanyRequired><Layout><TcsCollectedPage /></Layout></CompanyRequired></Protected>} />
      <Route path="/gstr1" element={<Protected><CompanyRequired><Layout><Gstr1FilingPage /></Layout></CompanyRequired></Protected>} />
      <Route path="/gstr3b" element={<Protected><CompanyRequired><Layout><Gstr3bWorksheetPage /></Layout></CompanyRequired></Protected>} />
      <Route path="/tds" element={<Protected><CompanyRequired><Layout><TdsReportPage /></Layout></CompanyRequired></Protected>} />
      <Route path="/cash-bank" element={<Protected><CompanyRequired><Layout><CashBankPage /></Layout></CompanyRequired></Protected>} />
      <Route path="/cash-bank/accounts" element={<Protected><CompanyRequired><Layout><CashBankAccountsPage /></Layout></CompanyRequired></Protected>} />
      <Route path="/invoices" element={<Protected><CompanyRequired><Layout><InvoicesPage /></Layout></CompanyRequired></Protected>} />
      <Route path="/quotations" element={<Protected><CompanyRequired><Layout><QuotationsPage /></Layout></CompanyRequired></Protected>} />
      <Route path="/delivery-challans" element={<Protected><CompanyRequired><Layout><DeliveryChallansPage /></Layout></CompanyRequired></Protected>} />
      <Route path="/delivery-challans/new" element={<Protected><CompanyRequired><Layout><DeliveryChallanFormPage /></Layout></CompanyRequired></Protected>} />
      <Route path="/delivery-challans/:id/edit" element={<Protected><CompanyRequired><Layout><DeliveryChallanFormPage /></Layout></CompanyRequired></Protected>} />
      <Route path="/invoice-dues" element={<Protected><CompanyRequired><Layout><InvoiceDuesPage /></Layout></CompanyRequired></Protected>} />
      <Route path="/invoices-view" element={<Protected><CompanyRequired><Layout><InvoicesAdvancedView /></Layout></CompanyRequired></Protected>} />
      <Route path="/credit-notes" element={<Protected><CompanyRequired><Layout><CreditNotesPage /></Layout></CompanyRequired></Protected>} />
      <Route path="/marketplace" element={<Protected><CompanyRequired><Layout><Suspense fallback={<div className="empty-state">Loading marketplace…</div>}><MarketplaceBrowsePage /></Suspense></Layout></CompanyRequired></Protected>} />
      <Route path="/marketplace/listings" element={<Protected><CompanyRequired><Layout><MyListingsPage /></Layout></CompanyRequired></Protected>} />
      <Route path="/marketplace/orders" element={<Protected><CompanyRequired><Layout><MarketplaceOrdersPage /></Layout></CompanyRequired></Protected>} />
      {/* ── Settings ───────────────────────────────────────────────── */}
      <Route path="/settings" element={<SettingsRoute requireCompany={false} setup="redirect"><SettingsOverviewPage /></SettingsRoute>} />
      <Route path="/settings/company" element={<SettingsRoute requireCompany={false} setup="frame"><CompanyPage /></SettingsRoute>} />
      <Route path="/settings/marketplace" element={<SettingsRoute admin><MarketplaceSettingsPage /></SettingsRoute>} />
      <Route path="/settings/email" element={<SettingsRoute platform><SmtpSettingsPage /></SettingsRoute>} />
      <Route path="/settings/email-history" element={<SettingsRoute admin><EmailHistoryPage /></SettingsRoute>} />
      <Route path="/settings/security" element={<SettingsRoute><ChangePasswordPage /></SettingsRoute>} />
      <Route path="/settings/shortcuts" element={<SettingsRoute><KeyboardShortcutsPage /></SettingsRoute>} />
      <Route path="/settings/appearance" element={<SettingsRoute requireCompany={false} setup="redirect"><AppearancePage /></SettingsRoute>} />
      <Route path="/settings/api-keys"element={<SettingsRoute admin><ApiKeysPage /></SettingsRoute>} />
      {/* Per-user, not admin-only: a user manages the connectors they themselves consented to. */}
      <Route path="/settings/connected-apps" element={<SettingsRoute><ConnectedAppsPage /></SettingsRoute>} />
      <Route path="/settings/backups" element={<SettingsRoute platform><BackupsPage /></SettingsRoute>} />

      {/* Where those pages used to live. */}
      {Object.entries(LEGACY_REDIRECTS).map(([from, to]) => (
        <Route key={from} path={from} element={<LegacyRedirect to={to} />} />
      ))}

      {/* Outside Protected/CompanyRequired/Layout on purpose: the visitor is a
          customer with a link, not a user of this app. */}
      <Route path="/s/:token" element={<PublicShareRedirect />} />

      <Route path="*" element={<Protected><CompanyRequired><Layout><NotFoundPage /></Layout></CompanyRequired></Protected>} />
    </Routes>
  );
}

export default function App() {
  return (
    /* The page transition in Layout and the dropdown animations moved
       regardless of the OS "reduce motion" setting — the stylesheet's
       prefers-reduced-motion block cannot reach a framer-motion animation
       because those are driven from JS. `reducedMotion="user"` makes every
       motion element in the tree drop its transform and layout animation when
       the user has asked for that, keeping only opacity. */
    <MotionConfig reducedMotion="user">
      <AuthProvider>
        <FYProvider>
          <ShortcutsProvider>
            <SessionEndedBridge />
            <AppRoutes />
            <WhatsAppSupportBubble />
          </ShortcutsProvider>
        </FYProvider>
      </AuthProvider>
    </MotionConfig>
  );
}
