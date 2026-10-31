"""Logging that never writes health data.

Unhandled exceptions are logged as exception type plus code locations only. Exception
messages are omitted because they can contain values (e.g. "could not convert '212'").
Access logs contain method, path and status; paths contain only opaque UUIDs.
"""

import logging
import traceback
import uuid

from starlette.responses import JSONResponse

logger = logging.getLogger("cardio")


def log_exception_without_message(exc: BaseException) -> str:
    error_id = uuid.uuid4().hex[:12]
    frames = traceback.extract_tb(exc.__traceback__)
    where = " <- ".join(f"{f.filename.rsplit('/', 1)[-1]}:{f.lineno}:{f.name}" for f in reversed(frames[-6:]))
    logger.error("error_id=%s type=%s at %s", error_id, type(exc).__name__, where)
    return error_id


class SafeErrorMiddleware:
    """Converts unhandled exceptions into a generic 500 without re-raising, so the server's
    default handler never logs the exception message."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        started = False

        async def tracking_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception as exc:
            error_id = log_exception_without_message(exc)
            if not started:
                await JSONResponse({"detail": "Internal error.", "error_id": error_id}, status_code=500)(
                    scope, receive, send
                )
