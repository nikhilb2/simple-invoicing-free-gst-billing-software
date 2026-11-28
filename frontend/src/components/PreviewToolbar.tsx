import { ReactNode, useCallback, useEffect, useRef } from 'react';
import { MoreHorizontal } from 'lucide-react';
import useMediaQuery, { PHONE_QUERY } from '../hooks/useMediaQuery';
import ModalCloseButton from './ModalCloseButton';

// Stable identity, so the click-outside effect does not resubscribe on every
// render of a preview that passes no menu handler at all.
const noop = () => {};

export type PreviewAction = {
  label: string;
  icon: ReactNode;
  onClick: () => void;
  disabled?: boolean;
  /** Falls back to `label` for the tooltip and the accessible name. */
  title?: string;
  /**
   * Stays in the button row on desktop, moves into the "…" menu on a phone.
   * A phone fits three controls on a row; the rest of a six-action toolbar is
   * what used to wrap the header into four rows.
   */
  overflowOnPhone?: boolean;
};

type PreviewToolbarProps = {
  eyebrow: string;
  title: string;
  titleId: string;
  /** Optional control displayed immediately beside the document title. */
  titleAdornment?: ReactNode;
  meta?: ReactNode;
  /** The one filled button. Everything else is quiet on purpose. */
  primary: PreviewAction;
  /**
   * Shown as quiet (ghost) buttons beside the primary. Keep to three — past
   * that, use the menu. They are deliberately not `--secondary`: that variant
   * is a solid blue gradient, so three filled buttons in a row read as three
   * competing primaries, which is the clutter this component exists to remove.
   */
  secondary?: PreviewAction[];
  /**
   * Behind the "…" button. Only for actions that are genuinely rare: an
   * overflow menu is somewhere you look once you already know what is inside
   * it, so anything a user opens the preview in order to do has to be in the
   * row instead.
   */
  menu?: PreviewAction[];
  /** Rendered above the menu items — for a setting rather than an action. */
  menuExtra?: ReactNode;
  /** Only needed when there is a menu or `menuExtra` to open. */
  menuOpen?: boolean;
  onMenuOpenChange?: (open: boolean) => void;
  onClose: () => void;
  closeLabel: string;
  /** Forces a layout. Left out, it follows the viewport (max-width 640px). */
  phone?: boolean;
};

/**
 * The header of a document preview: what you are looking at, then what you can
 * do with it.
 *
 * Shared by the invoice, receipt and statement previews so the same action sits
 * in the same place in all three. Each had grown its own row of five or six
 * equally loud buttons, which is what made them read as clutter — the fix is
 * one filled action, the rest quiet, the rare ones folded away, and the close
 * affordance pulled out of the row entirely and into the corner where a dialog
 * close belongs.
 */
export default function PreviewToolbar({
  eyebrow,
  title,
  titleId,
  titleAdornment,
  meta,
  primary,
  secondary = [],
  menu = [],
  menuExtra,
  menuOpen = false,
  onMenuOpenChange = noop,
  onClose,
  closeLabel,
  phone,
}: PreviewToolbarProps) {
  const viewportIsPhone = useMediaQuery(PHONE_QUERY);
  const isPhone = phone ?? viewportIsPhone;
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menuOpen) return;
    function handleClickOutside(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        onMenuOpenChange(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [menuOpen, onMenuOpenChange]);

  const runAndClose = useCallback((action: PreviewAction) => {
    onMenuOpenChange(false);
    action.onClick();
  }, [onMenuOpenChange]);

  const rowActions = isPhone ? secondary.filter((action) => !action.overflowOnPhone) : secondary;
  const phoneMenu = isPhone ? secondary.filter((action) => action.overflowOnPhone) : [];
  const hasMenu = phoneMenu.length > 0 || menu.length > 0 || Boolean(menuExtra);

  const primaryButton = (
    <button
      type="button"
      className="button button--primary"
      onClick={primary.onClick}
      disabled={primary.disabled}
      title={primary.title ?? primary.label}
      aria-label={primary.title ?? primary.label}
    >
      {primary.icon}
      {primary.label}
    </button>
  );

  const actionButton = (action: PreviewAction) => (
    <button
      key={action.label}
      type="button"
      className="button button--ghost"
      onClick={action.onClick}
      disabled={action.disabled}
      title={action.title ?? action.label}
      aria-label={action.title ?? action.label}
    >
      {action.icon}
      {action.label}
    </button>
  );

  const menuItem = (action: PreviewAction) => (
    <button
      key={action.label}
      type="button"
      className="action-dropdown__item"
      role="menuitem"
      onClick={() => runAndClose(action)}
      disabled={action.disabled}
      aria-label={action.title ?? action.label}
    >
      {action.icon}
      {action.label}
    </button>
  );

  const overflow = hasMenu ? (
    <div className="action-dropdown" ref={menuRef}>
      <button
        type="button"
        className="button button--ghost button--icon"
        onClick={() => onMenuOpenChange(!menuOpen)}
        aria-haspopup="true"
        aria-expanded={menuOpen}
        title="More actions"
        aria-label="More actions"
      >
        <MoreHorizontal size={16} aria-hidden="true" />
      </button>
      {menuOpen ? (
        <div className="action-dropdown__menu" role="menu">
          {phoneMenu.map(menuItem)}
          {menuExtra}
          {menu.map(menuItem)}
        </div>
      ) : null}
    </div>
  ) : null;

  const heading = titleAdornment ? (
    <div className="preview-header__heading-row">
      <h2 id={titleId} className="nav-panel__title">{title}</h2>
      {titleAdornment}
    </div>
  ) : (
    <h2 id={titleId} className="nav-panel__title">{title}</h2>
  );

  if (isPhone) {
    // Two siblings instead of one header, because only the title bar may stay
    // pinned: the pinned header used to hold every action, which on a 390px
    // screen was half the dialog. Close lives in the bar so it is reachable at
    // any scroll position; the actions scroll away with the document.
    const [firstRowAction, ...restActions] = rowActions;
    return (
      <>
        <div className="panel__header preview-header preview-header--bar no-print">
          <div className="preview-header__title">{heading}</div>
          <ModalCloseButton onClick={onClose} label={closeLabel} />
        </div>

        <div className="preview-actions no-print">
          {meta ? <p className="muted-text preview-header__meta">{meta}</p> : null}
          <div className="preview-toolbar preview-toolbar--phone">
            <div className="preview-toolbar__row">
              {primaryButton}
              {firstRowAction ? actionButton(firstRowAction) : null}
              {overflow}
            </div>
            {restActions.length > 0 ? (
              <div className="preview-toolbar__row preview-toolbar__row--rest" data-count={restActions.length}>
                {restActions.map(actionButton)}
              </div>
            ) : null}
          </div>
        </div>
      </>
    );
  }

  return (
    <div className="panel__header preview-header no-print">
      <div className="preview-header__title">
        <p className="eyebrow">{eyebrow}</p>
        {heading}
        {meta ? <p className="muted-text preview-header__meta">{meta}</p> : null}
      </div>

      <div className="preview-header__actions">
        <div className="button-row preview-toolbar">
          {primaryButton}
          {rowActions.map(actionButton)}
          {overflow}
        </div>

        <ModalCloseButton onClick={onClose} label={closeLabel} />
      </div>
    </div>
  );
}
