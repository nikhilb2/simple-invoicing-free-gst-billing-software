/**
 * How far to scroll the page down so that `target` (the Start billing button)
 * is fully above the bottom of the visible area (the top of a phone keyboard),
 * without pushing the focused field off the top. All values are in viewport
 * px, as from getBoundingClientRect. Returns 0 when nothing needs to move.
 */
export function keepInViewScroll({
  targetBottom,
  viewportBottom,
  focusedTop,
  margin = 8,
}: {
  targetBottom: number;
  viewportBottom: number;
  focusedTop: number;
  margin?: number;
}): number {
  const needed = targetBottom + margin - viewportBottom;
  if (needed <= 0) return 0;
  const room = Math.max(0, focusedTop - margin);
  return Math.min(needed, room);
}

/** The bottom edge of what the user can see: the visual viewport when the browser has one. */
export function visibleViewportBottom(win: Window = window): number {
  const vv = win.visualViewport;
  return vv ? vv.offsetTop + vv.height : win.innerHeight;
}
