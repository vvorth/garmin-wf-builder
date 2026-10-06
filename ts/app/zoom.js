// Zoom and real size: pure functions, no DOM, so Node can check them
// (tests/test_studio_frontend.py).
//
// The zoom is CSS pixels per watch pixel. The server draws at a whole
// scale (1 to 4); the browser shows that image at the zoom, so the server
// draws at the smallest scale that is not blurred at the zoom on this
// screen.
//
// A browser does not know the size of its screen's pixels: CSS defines an
// inch as 96 CSS pixels, which matches a real inch only on some screens.
// Real size is therefore the watch's own size (its pixels over its pixels
// per inch) in CSS inches, times a calibration the author makes once by
// matching a bank card on the screen.

export const MIN_ZOOM = 0.2;
export const MAX_ZOOM = 4;
export const CSS_PX_PER_INCH = 96;
// ISO/IEC 7810 ID-1, every bank card: 85.60 mm by 53.98 mm.
export const CARD_MM = [85.6, 53.98];

export function clampZoom(zoom) {
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom));
}

// The scale to ask the server for: the zoom in device pixels, rounded up.
export function serverScale(zoom, devicePixelRatio = 1) {
  return Math.min(4, Math.max(1, Math.ceil(zoom * devicePixelRatio - 1e-9)));
}

// The zoom that shows a watch of `ppi` at its real size, given how many
// CSS pixels make a real inch on this screen; null when the watch's files
// give no pixel density.
export function realZoom(ppi, cssPxPerInch = CSS_PX_PER_INCH) {
  if (!(ppi > 0)) return null;
  return cssPxPerInch / ppi;
}

// CSS pixels per real inch, from a card's measured width in CSS pixels.
export function calibrate(cardWidthCssPx) {
  return (cardWidthCssPx / CARD_MM[0]) * 25.4;
}

// The watch's screen in millimetres, for the label beside the notch.
export function screenMm(width, ppi) {
  return ppi > 0 ? (width / ppi) * 25.4 : null;
}
