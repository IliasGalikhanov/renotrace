"""Synthetic demos and expiring private guest reviews. No account registration."""

import os
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.demo.routes import router as demo_router
from app.guest.models import Problem
from app.guest.routes import router as guest_router
from app.guest.runtime import lifespan

app = FastAPI(title="RenoTrace API", version="0.9.0", lifespan=lifespan)
app.include_router(demo_router)
app.include_router(guest_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.environ.get("FRONTEND_ORIGIN", "http://127.0.0.1:3100")],
    allow_methods=["GET", "PUT"],
    allow_headers=["Authorization", "Content-Type"],
    allow_credentials=False,
)


@app.exception_handler(Problem)
async def guest_problem(request: Request, error: Problem) -> JSONResponse:
    return JSONResponse(
        status_code=error.status,
        content={"detail": error.message},
        headers={"Cache-Control": "no-store"},
    )


class Health(BaseModel):
    status: Literal["ok"]
    service: Literal["renotrace-api"]


@app.get("/healthz", response_model=Health)
def health() -> Health:
    return Health(status="ok", service="renotrace-api")
