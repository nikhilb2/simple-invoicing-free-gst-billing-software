export const ACTIVE_ATTRIBUTE = 'data-tour-active';

type Markable = Pick<Element, 'setAttribute' | 'removeAttribute'>;

/**
 * Keeps `data-tour-active` on exactly one element: the one the guide points at.
 * Marking another element, or nothing, takes it off the previous one. The CSS for
 * the attribute draws the outline, so nothing else follows the element around.
 */
export function createActiveMarker() {
  let active: Markable | null = null;
  return {
    mark(element: Markable | null) {
      if (element === active) return;
      active?.removeAttribute(ACTIVE_ATTRIBUTE);
      element?.setAttribute(ACTIVE_ATTRIBUTE, '');
      active = element;
    },
  };
}

/** Gap kept between the target and the sticky header, and between the target and the card. */
export const HEADER_GAP = 8;
export const CARD_GAP = 12;

export type BandInput = {
  /** Top and bottom of what the screen shows (the visual viewport, so the phone keyboard counts). */
  viewportTop: number;
  viewportBottom: number;
  /** Bottom of the sticky app header, or null when nothing sticky covers the top (a dialog sits above it). */
  headerBottom: number | null;
  /** The card's box, or null when there is none. */
  card: { top: number; bottom: number } | null;
};

/**
 * The part of the screen a target must sit wholly inside: from 8px under the sticky
 * header to 12px above the card. A card at the top of the screen (the target is in the
 * fixed Create invoice bar) bounds the band from above instead.
 */
export function visibleBand({ viewportTop, viewportBottom, headerBottom, card }: BandInput): { top: number; bottom: number } {
  let top = viewportTop;
  let bottom = viewportBottom;
  if (headerBottom !== null) top = Math.max(top, headerBottom + HEADER_GAP);
  if (card) {
    const middle = (viewportTop + viewportBottom) / 2;
    if (card.top + card.bottom < 2 * middle) top = Math.max(top, card.bottom + CARD_GAP);
    else bottom = Math.min(bottom, card.top - CARD_GAP);
  }
  return { top, bottom };
}

/** Whether the target's whole box is inside the band. */
export function isWithinBand(rect: { top: number; bottom: number }, band: { top: number; bottom: number }): boolean {
  return rect.top >= band.top && rect.bottom <= band.bottom;
}

/**
 * How long typing must pause, once the required field holds a value, before the
 * walkthrough moves on to the next step without waiting for the field to blur.
 */
export const TYPING_PAUSE_MS = 600;

/**
 * Whether a focused field is still being typed in. It stops being so once it holds a
 * value and nothing has been typed for TYPING_PAUSE_MS, so the walkthrough can move on
 * without the field losing focus. `msSinceInput` is null when nothing was typed in it.
 */
export function stillTyping(focused: boolean, value: string, msSinceInput: number | null): boolean {
  if (!focused) return false;
  if (msSinceInput === null || value.trim() === '') return true;
  return msSinceInput < TYPING_PAUSE_MS;
}
