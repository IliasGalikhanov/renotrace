"""Explicit schema installation and retention maintenance; no credentials in output."""

import sys
from threading import Event

from .runtime import configured_reviews


def main() -> None:
    reviews = configured_reviews()
    if reviews is None:
        raise SystemExit("Set DATABASE_URL and private object-store configuration first")
    action = sys.argv[1] if len(sys.argv) == 2 else ""
    if action == "migrate":
        reviews.db.migrate()
    elif action == "cleanup":
        reviews.cleanup()
    elif action == "worker":
        reviews.run(Event())
    else:
        raise SystemExit("Usage: python -m app.guest.manage migrate|cleanup|worker")


if __name__ == "__main__":
    main()
