import { useEffect } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { ChevronsLeft, ChevronRight, LogOut } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { Link, NavLink, useLocation } from 'react-router-dom';
import api from '../api/client';
import type { CompanyProfile } from '../types/api';
import { COMPANY_SETUP_PATH, isCompanySetupRequired } from '../utils/companySetup';
import BrandMark from './BrandMark';
import SidebarFYSwitcher from './SidebarFYSwitcher';
import { SETTINGS_ENTRY, sectionIdForPath, visiblePrimaryNav, type NavLeaf } from '../config/navigation';
import { useAuth } from '../context/AuthContext';
import { useSidebarStore } from '../store/useSidebarStore';

interface SidebarProps {
  isOpen?: boolean;
  onClose?: () => void;
}

function linkClass(isActive: boolean, extra = '') {
  return `sidebar__link${extra}${isActive ? ' sidebar__link--active' : ''}`;
}

export default function Sidebar({ isOpen = false, onClose }: SidebarProps) {
  const { isAdmin, canManagePlatform, userEmail, logout } = useAuth();
  const { collapsed, toggleCollapsed, openSection, toggleSection, openSectionFor } = useSidebarStore();
  const location = useLocation();
  const currentSection = sectionIdForPath(location.pathname);

  // Same key as the route guard, so saving the company (which invalidates it)
  // flips this back without a reload.
  const companyQuery = useQuery({
    queryKey: ['company-setup-required'],
    queryFn: async () => (await api.get<CompanyProfile>('/company/')).data,
    retry: false,
  });
  const setupRequired = isCompanySetupRequired(companyQuery.data, companyQuery.error, companyQuery.isLoading);
  const entries = visiblePrimaryNav(isAdmin, canManagePlatform, companyQuery.data?.enable_tcs === true);

  // Escape-to-close lives in Layout, which owns the drawer state.

  // Arriving inside a section opens it. Manual toggles are left alone: this
  // only fires when the path changes, so a section the user opened by hand
  // while staying put stays open.
  useEffect(() => {
    if (currentSection) openSectionFor(currentSection);
  }, [currentSection, openSectionFor]);

  // Until a company exists every page bounces back to setup, so these rows
  // are shown as unavailable instead of silently doing nothing.
  const renderLocked = (key: string, label: string, Icon: NavLeaf['icon'], extraClass = '') => (
    <span
      key={key}
      className={`sidebar__link sidebar__link--disabled${extraClass}`}
      role="link"
      aria-disabled="true"
      title="Save your company details to open this page"
    >
      <Icon size={18} aria-hidden="true" />
      <span className="sidebar__link-label">{label}</span>
    </span>
  );

  const renderLeaf = (item: NavLeaf, extraClass = '') => {
    const Icon = item.icon;
    if (setupRequired && item !== SETTINGS_ENTRY) return renderLocked(item.to, item.label, Icon, extraClass);
    if (setupRequired) {
      return (
        <NavLink
          key={item.to}
          to={COMPANY_SETUP_PATH}
          className={({ isActive }) => linkClass(isActive, extraClass)}
          onClick={() => onClose?.()}
          title="Company setup"
        >
          <Icon size={18} aria-hidden="true" />
          <span className="sidebar__link-label">Company setup</span>
        </NavLink>
      );
    }
    return (
      <NavLink
        key={item.to}
        to={item.to}
        end={item.end}
        className={({ isActive }) => linkClass(isActive, extraClass)}
        onClick={() => onClose?.()}
        // Tooltip stands in for the label once the rail collapses.
        title={item.label}
      >
        <Icon size={18} aria-hidden="true" />
        <span className="sidebar__link-label">{item.label}</span>
      </NavLink>
    );
  };

  return (
    <aside
      className={`sidebar${isOpen ? ' sidebar--open' : ''}`}
      {...(isOpen ? { role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Navigation drawer' } : {})}
    >
      <div className="sidebar__header">
        <button
          className="sidebar__close"
          onClick={onClose}
          aria-label="Close navigation"
        >
          ✕
        </button>
        <Link to="/" className="sidebar__brand" onClick={() => onClose?.()}>
          <BrandMark size={28} />
          <div>
            <span className="sidebar__brand-name">Simple Invoicing</span>
            <span className="sidebar__brand-tagline">Stock &amp; billing</span>
          </div>
        </Link>
        <button
          type="button"
          className={`sidebar__collapse${collapsed ? ' sidebar__collapse--collapsed' : ''}`}
          onClick={toggleCollapsed}
          aria-label={collapsed ? 'Expand navigation' : 'Collapse navigation'}
          aria-expanded={!collapsed}
          aria-controls="sidebar-nav"
          title={collapsed ? 'Expand navigation' : 'Collapse navigation'}
        >
          {/* One chevron that rotates rather than two icons that swap: the
              turn is what tells you which way the rail is about to move. */}
          <ChevronsLeft size={18} aria-hidden="true" />
        </button>
      </div>

      <nav className="sidebar__nav" id="sidebar-nav" aria-label="Sidebar navigation">
        {setupRequired && (
          <p className="sidebar__setup-note" role="note">
            Save your company details to open the rest of the app.
          </p>
        )}
        {entries.map((entry) => {
          if (entry.kind === 'link') return renderLeaf(entry);

          const Icon = entry.icon;
          if (setupRequired) return renderLocked(entry.id, entry.label, Icon);
          const isCurrent = currentSection === entry.id;

          // A 68px rail has no room to expand into, and a disclosure that
          // opens onto clipped labels is a dead end — so the rail links
          // straight to the section's first page instead.
          if (collapsed) {
            return (
              <NavLink
                key={entry.id}
                to={entry.children[0].to}
                className={linkClass(isCurrent, ' sidebar__link--rail-section')}
                onClick={() => onClose?.()}
                title={entry.label}
              >
                <Icon size={18} aria-hidden="true" />
                <span className="sidebar__link-label">{entry.label}</span>
              </NavLink>
            );
          }

          const isExpanded = openSection === entry.id;
          return (
            <div className="sidebar__section" key={entry.id}>
              <button
                type="button"
                className={`sidebar__link sidebar__section-toggle${isCurrent ? ' sidebar__section-toggle--current' : ''}`}
                onClick={() => toggleSection(entry.id)}
                aria-expanded={isExpanded}
                aria-controls={`nav-section-${entry.id}`}
              >
                <Icon size={18} aria-hidden="true" />
                <span className="sidebar__link-label">{entry.label}</span>
                <ChevronRight
                  size={15}
                  aria-hidden="true"
                  className={`sidebar__chevron${isExpanded ? ' sidebar__chevron--open' : ''}`}
                />
              </button>

              <AnimatePresence initial={false}>
                {isExpanded && (
                  <motion.div
                    id={`nav-section-${entry.id}`}
                    className="sidebar__section-items"
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: 'auto', opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.18, ease: 'easeOut' }}
                  >
                    {entry.children.map((child) => renderLeaf(child, ' sidebar__link--child'))}
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          );
        })}
      </nav>

      <SidebarFYSwitcher />

      <div className="sidebar__footer">
        {renderLeaf(SETTINGS_ENTRY, ' sidebar__link--settings')}

        <div className="sidebar__user">
          <div className="sidebar__user-avatar">
            {userEmail ? userEmail[0].toUpperCase() : 'U'}
          </div>
          <div className="sidebar__user-meta">
            <span className="sidebar__user-email" title={userEmail ?? undefined}>{userEmail ?? 'Active user'}</span>
            <span className="sidebar__user-role">{isAdmin ? 'Admin' : 'User'}</span>
          </div>
        </div>
        <button className="button button--ghost sidebar__logout" onClick={logout} title="Logout">
          <LogOut size={16} aria-hidden="true" />
          <span className="sidebar__link-label">Logout</span>
        </button>
      </div>
    </aside>
  );
}
