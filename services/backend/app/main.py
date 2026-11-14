"""HTTP foundation only; private financial API is not implemented in stage 1."""

from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="RenoTrace", version="0.1.0")


class Health(BaseModel):
    status: Literal["ok"]
    service: Literal["renotrace-api"]


@app.get("/healthz", response_model=Health)
def health() -> Health:
    return Health(status="ok", service="renotrace-api")
