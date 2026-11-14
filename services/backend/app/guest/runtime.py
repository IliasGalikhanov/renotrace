"""Optional guest runtime: the public synthetic demo needs no database or storage."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from threading import Event, Thread

from fastapi import FastAPI

from .database import Database
from .service import Reviews
from .storage import configured_store


def configured_reviews() -> Reviews | None:
    if not os.environ.get("DATABASE_URL"):
        return None
    return Reviews(Database(os.environ["DATABASE_URL"]), configured_store())


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    reviews = configured_reviews()
    app.state.reviews = reviews
    stop = Event()
    thread: Thread | None = None
    if reviews and os.environ.get("REVIEW_WORKER", "1") == "1":
        thread = Thread(target=reviews.run, args=(stop,), daemon=True, name="guest-extraction")
        thread.start()
    yield
    stop.set()
    if thread:
        thread.join(timeout=2)
