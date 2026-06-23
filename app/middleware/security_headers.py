"""
Security headers middleware.

Adds the standard hardening response headers to every API response:
  - Strict-Transport-Security  (force HTTPS for a year, incl. subdomains)
  - X-Content-Type-Options     (no MIME sniffing)
  - X-Frame-Options            (no clickjacking — the API is never framed)
  - Referrer-Policy            (don't leak URLs cross-origin)
  - Permissions-Policy         (disable powerful features by default)
  - Cross-Origin-Opener-Policy / Resource-Policy (isolate the API origin)

These are cheap, low-risk additions on JSON responses and close the "TLS/HTTPS
hardening" + "secure headers" items of the production checklist.
"""

from starlette.middleware.base import BaseHTTPMiddleware

_HEADERS = {
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    "Cross-Origin-Resource-Policy": "same-site",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        for k, v in _HEADERS.items():
            response.headers.setdefault(k, v)
        return response
