"""Local-only request guard. This is not authentication (decision D-004).

- Host header must be on the allowlist (DNS-rebinding defense).
- State-changing requests must carry the X-Cardio-Client header, which a cross-site HTML
  form cannot set and which forces a CORS preflight that this API never approves.
- If an Origin header is present on a state-changing request, it must be allowlisted.
- No CORS middleware is installed, so browsers block cross-origin reads.
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import get_settings

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
CLIENT_HEADER = "x-cardio-client"


class LocalRequestGuard(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        settings = get_settings()
        host = (request.headers.get("host") or "").rsplit(":", 1)[0].strip("[]")
        if host not in settings.allowed_host_list:
            return JSONResponse({"detail": "Host not allowed."}, status_code=400)
        if request.method not in SAFE_METHODS:
            if request.headers.get(CLIENT_HEADER) != "web":
                return JSONResponse({"detail": "Missing client header."}, status_code=403)
            origin = request.headers.get("origin")
            if origin is not None and origin not in settings.allowed_origin_list:
                return JSONResponse({"detail": "Origin not allowed."}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response
