"""Health and public synthetic demo only; private case APIs are not implemented."""

from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

from app.demo.routes import router as demo_router

app = FastAPI(title="RenoTrace demo API", version="0.4.0")
app.include_router(demo_router)


class Health(BaseModel):
    status: Literal["ok"]
    service: Literal["renotrace-api"]


@app.get("/healthz", response_model=Health)
def health() -> Health:
    return Health(status="ok", service="renotrace-api")
