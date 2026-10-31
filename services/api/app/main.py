import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.logging_safe import SafeErrorMiddleware
from app.routers import documents, observations, partner, research, review
from app.security import LocalRequestGuard
from app.services.records import DomainError

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Cardio Research API",
        version="0.2.0",
        description="Verified longitudinal records and a research partner over them. No risk estimates, "
        "prescriptions or test orders.",
    )
    app.add_middleware(LocalRequestGuard)
    app.add_middleware(SafeErrorMiddleware)  # outermost: nothing below it can leak an exception message

    @app.exception_handler(DomainError)
    async def domain_error(_: Request, exc: DomainError):
        return JSONResponse({"detail": exc.message, "info": exc.detail}, status_code=exc.status_code)

    @app.get("/api/v1/health", tags=["health"])
    def health():
        return {"status": "ok"}

    for r in (documents.router, observations.router, review.router, research.router, partner.router,
              partner.context_router):
        app.include_router(r, prefix="/api/v1")
    return app


app = create_app()
