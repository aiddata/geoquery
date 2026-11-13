/**
 * The narrowest layout GeoQuery supports, in CSS px. Narrower devices get a
 * zoomed-out 1024px layout (the script in app.html, which must use the same
 * number), and narrower desktop windows stop shrinking here and scroll
 * sideways (layout.css). SmallScreenNotice explains either case.
 */
export const MIN_LAYOUT_WIDTH = 1024;

export const NOTICE_DISMISSED_KEY = 'geoquery-small-screen-dismissed';
