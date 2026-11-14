"""Preserve the verified stateless release before the first guest rollout.

Fail if guest data exists: this script must not pretend an empty-state snapshot backs it up.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from app.guest.runtime import configured_reviews

reviews = configured_reviews()
assert reviews is not None
with reviews.db.connection() as connection:
    projects = connection.execute("SELECT count(*) AS n FROM guest_review.projects").fetchone()
    objects = connection.execute("SELECT count(*) AS n FROM guest_review.objects").fetchone()
assert projects and projects["n"] == 0, "Guest data exists; a real private data backup is required"
assert objects and objects["n"] == 0, "Object outbox is not empty; finish cleanup before rollout"
root = Path(__file__).resolve().parents[1]
destination = root / "backups" / "stage6-before-release"
destination.mkdir(parents=True, exist_ok=True)
manifest = {
    "captured_at": datetime.now(UTC).isoformat(),
    "previous_release_sha": "e76b358f9ef374a4f3f0f0ca0c81d147aabef06e",
    "frontend": "https://renotrace.vercel.app",
    "frontend_deployment": "dpl_F3sDZ9nNAUQ89jreMbdGMuhZmUXH",
    "backend": "https://renotrace-api.onrender.com",
    "backend_deployment": "dep-dbs9ifd6e07s7397scug",
    "previous_release_persisted_guest_data": False,
    "new_schema_projects": 0,
    "new_schema_objects": 0,
    "restore_policy": (
        "Roll back code to the previous SHA; keep database and retention cleanup. "
        "Never restore deleted or expired reviews."
    ),
}
(destination / "release.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
(destination / "initial-guest-schema.sql").write_bytes(
    (root / "services/backend/app/guest/schema.sql").read_bytes()
)
print(
    "Stateless stage 5 release snapshot saved privately; "
    "new guest database and object outbox are empty"
)
