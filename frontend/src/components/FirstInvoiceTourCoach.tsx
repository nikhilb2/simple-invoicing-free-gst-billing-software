import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useLocation, useNavigate } from 'react-router-dom';
import {
  AWAY_GUIDE,
  forPointer,
  guideFor,
  INVOICE_PATH,
  pickTarget,
  TOUR_STEPS,
  type FieldState,
  type Guide,
  type GuideTarget,
} from '../features/firstInvoiceTour/tourSteps';
import { createActiveMarker, isWithinBand, stillTyping, visibleBand } from '../features/firstInvoiceTour/activeTarget';
import { useAuthStore } from '../store/useAuthStore';
import { useFirstInvoiceTourStore } from '../store/useFirstInvoiceTourStore';


function visibleElement(selector: string): HTMLElement | null {
  const element = document.querySelector<HTMLElement>(selector);
  if (!element) return null;
  const { width, height } = element.getBoundingClientRect();
  return width > 0 && height > 0 ? element : null;
}

/** When each field was last typed in. A paused field counts as filled in without losing focus. */
const lastInputAt = new WeakMap<EventTarget, number>();

function readField(selector: string): FieldState {
  const element = visibleElement(selector);
  if (!element) return { visible: false, value: '', focused: false };
  const value = (element as HTMLInputElement).value ?? '';
  const at = lastInputAt.get(element);
  const since = at === undefined ? null : Date.now() - at;
  return {
    visible: true,
    value,
    focused: stillTyping(document.activeElement === element, value, since),
  };
}

export function isCoarsePointer(): boolean {
  return typeof window !== 'undefined' && !!window.matchMedia?.('(pointer: coarse)').matches;
}

/** The phone keyboard is up when it takes a quarter or more of the screen. */
export function keyboardIsOpen(): boolean {
  const viewport = window.visualViewport;
  return !!viewport && isCoarsePointer() && viewport.height < window.innerHeight * 0.75;
}

/**
 * Follows which element the guide points at. Dialogs open and fields fill in, so
 * the pick is re-read every frame, but the page is only touched when the pick
 * changes: the target itself carries `data-tour-active`, and the outline then
 * scrolls, clips and stays put with it like any other style.
 */
function useTarget(guide: Guide | null): GuideTarget | null {
  const [target, setTarget] = useState<GuideTarget | null>(null);
  const picked = useRef<GuideTarget | null>(null);

  useEffect(() => {
    const marker = createActiveMarker();
    const publish = (next: GuideTarget | null) => {
      if (picked.current === next) return;
      picked.current = next;
      setTarget(next);
    };
    if (!guide) {
      publish(null);
      return undefined;
    }

    const noteInput = (event: Event) => {
      if (event.target) lastInputAt.set(event.target, Date.now());
    };
    document.addEventListener('input', noteInput, true);
    document.addEventListener('change', noteInput, true);

    let frame = 0;
    const tick = () => {
      const next = pickTarget(guide, readField);
      const element = next ? visibleElement(next.selector) : null;
      marker.mark(element);
      publish(element ? next : null);
      frame = requestAnimationFrame(tick);
    };
    tick();
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener('input', noteInput, true);
      document.removeEventListener('change', noteInput, true);
      marker.mark(null);
    };
  }, [guide]);

  return target;
}

/** Bottom of the sticky app header, measured; null when it is not on the page or a dialog covers it. */
function stickyHeaderBottom(element: HTMLElement): number | null {
  if (element.closest('.modal-panel')) return null;
  const header = document.querySelector<HTMLElement>('.page-header');
  if (!header || window.getComputedStyle(header).position !== 'sticky') return null;
  return header.getBoundingClientRect().bottom;
}

/** Whether the element can be seen and used: wholly inside the band between the sticky header and the card, and inside its dialog's panel. */
function isInClearView(element: HTMLElement, card: HTMLElement | null): boolean {
  const rect = element.getBoundingClientRect();
  const viewport = window.visualViewport;
  const viewportTop = viewport?.offsetTop ?? 0;
  const band = visibleBand({
    viewportTop,
    viewportBottom: viewportTop + (viewport?.height ?? window.innerHeight),
    headerBottom: stickyHeaderBottom(element),
    card: card ? card.getBoundingClientRect() : null,
  });
  if (!isWithinBand(rect, band)) return false;
  const panel = element.closest<HTMLElement>('.modal-panel');
  if (panel) {
    const box = panel.getBoundingClientRect();
    if (rect.top < box.top || rect.bottom > box.bottom) return false;
  }
  return true;
}

/**
 * True when the element sits in the composer's fixed Create invoice bar (on a phone). Scrolling can't move it clear of the card, so the card goes to the top.
 */
export function inFixedBar(element: HTMLElement | null): boolean {
  // Only the composer's bar: dialogs are fixed too, but their targets scroll clear of the card.
  const bar = element?.closest<HTMLElement>('.composer-submit');
  return !!bar && window.getComputedStyle(bar).position === 'fixed';
}

/**
 * Makes room for the floating card, so pages and dialogs can always scroll what
 * they hold clear of it. On a phone it would otherwise sit on a form's Save button.
 */
export function useReserveCardSpace(cardRef: React.RefObject<HTMLElement>, visible: boolean): void {
  useLayoutEffect(() => {
    const root = document.documentElement;
    if (!visible) return;
    root.setAttribute('data-tour-card', '');
    root.style.setProperty('--tour-card-height', `${cardRef.current?.getBoundingClientRect().height ?? 0}px`);
  });
  useLayoutEffect(() => {
    if (!visible) return undefined;
    const root = document.documentElement;
    return () => {
      root.removeAttribute('data-tour-card');
      root.style.removeProperty('--tour-card-height');
    };
  }, [visible]);
}

export type CoachCardProps = {
  step: number;
  title: string;
  body: string;
  done?: boolean;
  onExit?: () => void;
  onFinish?: () => void;
  onBackToInvoice?: () => void;
  cardRef?: React.Ref<HTMLElement>;
  placeOnTop?: boolean;
};

export function CoachCard({ step, title, body, done, onExit, onFinish, onBackToInvoice, cardRef, placeOnTop }: CoachCardProps) {
  return (
    <section
      ref={cardRef}
      className={`tour-coach${placeOnTop ? ' tour-coach--top' : ''}`}
      aria-label="First invoice walkthrough"
      data-testid="tour-coach"
    >
      <div className="tour-coach__progress" aria-hidden="true">
        {Array.from({ length: TOUR_STEPS }, (_, index) => (
          <span key={index} className={index < step || done ? 'tour-coach__dot tour-coach__dot--on' : 'tour-coach__dot'} />
        ))}
      </div>
      <p className="eyebrow">{done ? 'All done' : `Step ${step} of ${TOUR_STEPS}`}</p>
      <div aria-live="polite">
        <h2 className="tour-coach__title">{title}</h2>
        <p className="tour-coach__body">{body}</p>
      </div>
      <div className="tour-coach__actions">
        {onBackToInvoice ? (
          <button type="button" className="button button--primary tour-coach__button" onClick={onBackToInvoice}>
            Back to the invoice
          </button>
        ) : null}
        {onFinish ? (
          <button type="button" className="button button--primary tour-coach__button" onClick={onFinish}>
            Finish
          </button>
        ) : null}
        {onExit ? (
          <button type="button" className="button button--ghost tour-coach__button" onClick={onExit}>
            Exit walkthrough
          </button>
        ) : null}
      </div>
    </section>
  );
}

/**
 * Guides the first invoice from a card that sits beside the real page.
 *
 * Nothing is dimmed or blocked: people are typing into real forms, dialogs and
 * dropdowns, and a step only moves on when the customer, product or invoice has
 * actually been saved. That is why this is not built on a tour library, whose
 * overlays are made for clicking Next through a page.
 */
export default function FirstInvoiceTourCoach() {
  const phase = useFirstInvoiceTourStore((state) => state.phase);
  const owner = useFirstInvoiceTourStore((state) => state.owner);
  const facts = useFirstInvoiceTourStore((state) => state.facts);
  const exit = useFirstInvoiceTourStore((state) => state.exit);
  const close = useFirstInvoiceTourStore((state) => state.close);
  const userEmail = useAuthStore((state) => state.userEmail);
  const { pathname } = useLocation();
  const navigate = useNavigate();

  const mine = owner === userEmail;
  const onInvoicePage = pathname === INVOICE_PATH;
  const guide = phase === 'running' && mine ? (onInvoicePage ? guideFor(facts) : AWAY_GUIDE) : null;
  const target = useTarget(guide);

  const cardRef = useRef<HTMLElement>(null);
  const finished = phase === 'done' && mine;

  // While the phone keyboard is up the field's own label says what to type, and the card
  // would only sit on the little dialog that is left.
  const [keyboardOpen, setKeyboardOpen] = useState(keyboardIsOpen);
  useEffect(() => {
    const viewport = window.visualViewport;
    if (!viewport) return undefined;
    const update = () => setKeyboardOpen(keyboardIsOpen());
    viewport.addEventListener('resize', update);
    window.addEventListener('resize', update);
    return () => {
      viewport.removeEventListener('resize', update);
      window.removeEventListener('resize', update);
    };
  }, []);

  const showCard = (finished || guide !== null) && !keyboardOpen;
  useReserveCardSpace(cardRef, showCard);

  // Bring the target into view when it changes and when the keyboard opens or closes: on
  // screen, clear of the card, and inside its dialog. scrollIntoView moves the dialog's own scroller too.
  const selector = target?.selector ?? null;
  useEffect(() => {
    if (!selector) return undefined;
    const bringIntoView = () => {
      const element = visibleElement(selector);
      if (!element || isInClearView(element, cardRef.current)) return;
      const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
      element.scrollIntoView({ block: 'center', behavior: reduceMotion ? 'auto' : 'smooth' });
    };
    // The card and the dialog settle a frame after the target changes, and the page can
    // still shift after that (an empty-state block that is loading), so check again on the
    // next two frames and whenever the target, the page or its dialog changes size.
    let frame = 0;
    const later = (frames: number) => {
      cancelAnimationFrame(frame);
      const step = (left: number) => {
        frame = requestAnimationFrame(() => {
          bringIntoView();
          if (left > 1) step(left - 1);
        });
      };
      step(frames);
    };
    later(2);
    const onResize = () => later(2);
    const viewport = window.visualViewport;
    viewport?.addEventListener('resize', onResize);
    let observer: ResizeObserver | undefined;
    if (typeof ResizeObserver !== 'undefined') {
      observer = new ResizeObserver(onResize);
      const element = visibleElement(selector);
      if (element) observer.observe(element);
      observer.observe(document.body);
      const panel = element?.closest('.modal-panel');
      if (panel) observer.observe(panel);
    }
    return () => {
      cancelAnimationFrame(frame);
      observer?.disconnect();
      viewport?.removeEventListener('resize', onResize);
    };
  }, [selector]);

  // A target in the fixed bar (Create invoice on a phone) can't scroll clear of the
  // card, so the card goes to the top, as in the #1117 mockup for the create step.
  const [placeOnTop, setPlaceOnTop] = useState(false);
  useLayoutEffect(() => {
    const element = selector ? visibleElement(selector) : null;
    const update = () => setPlaceOnTop(inFixedBar(element));
    update();
    window.addEventListener('resize', update);
    return () => window.removeEventListener('resize', update);
  }, [selector]);

  if (finished) {
    return !showCard ? null : createPortal(
      <CoachCard
        cardRef={cardRef}
        step={TOUR_STEPS}
        done
        title="Your first invoice is ready"
        body="Use Share, Email or Download at the top of the preview to send it to your customer. You’ll find it under Invoices from now on."
        onFinish={close}
      />,
      document.body,
    );
  }

  if (!guide || !showCard) return null;

  const coarse = isCoarsePointer();
  return createPortal(
    <CoachCard
      cardRef={cardRef}
      step={guide.step}
      title={forPointer(target?.title ?? guide.title, coarse)}
      body={forPointer(target?.body ?? guide.body, coarse)}
      placeOnTop={placeOnTop}
      onExit={exit}
      onBackToInvoice={onInvoicePage ? undefined : () => navigate(INVOICE_PATH)}
    />,
    document.body,
  );
}
