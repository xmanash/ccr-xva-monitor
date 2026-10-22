"""FastAPI application."""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from ccr_xva import __version__
from ccr_xva.api.routes import router


def create_app() -> FastAPI:
    try:
        import truststore

        truststore.inject_into_ssl()
    except Exception:
        pass
    app = FastAPI(title="CCR-XVA Monitor", version=__version__)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router, prefix="/api/v1")

    @app.get("/")
    def root() -> dict:
        return {
            "name": "CCR-XVA Monitor",
            "version": __version__,
            "health": "/api/v1/health",
            "docs": "/docs",
            "api": "/api/v1",
        }

    @app.exception_handler(ValueError)
    async def value_error(_request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(NotImplementedError)
    async def not_implemented(_request: Request, exc: NotImplementedError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    return app


app = create_app()


def run() -> None:
    import uvicorn

    uvicorn.run("ccr_xva.api.main:app", host="0.0.0.0", port=8000, reload=False)
