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
