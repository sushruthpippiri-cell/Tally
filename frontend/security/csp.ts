/** The app's Content Security Policy (D-051 #4). One source for `vite preview` and, in P16,
 * the production reverse proxy: no inline script or style, nothing from another origin. */
export const CSP = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self'",
  "img-src 'self' data:",
  "font-src 'self'",
  "connect-src 'self'",
  "object-src 'none'",
  "base-uri 'none'",
  "form-action 'self'",
  "frame-ancestors 'none'",
  // No upgrade-insecure-requests: WebKit applies it even to http://localhost (it broke Safari
  // in development), and production is HTTPS with HSTS, where every 'self' source is https.
].join("; ");

export const SECURITY_HEADERS: Record<string, string> = {
  "Content-Security-Policy": CSP,
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "no-referrer",
};
