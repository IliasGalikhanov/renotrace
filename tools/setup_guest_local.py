"""Initialize only the dedicated local Compose test services (no production credentials)."""

import time

from botocore.exceptions import ConnectionClosedError, EndpointConnectionError, ReadTimeoutError

from app.guest.database import Database
from app.guest.storage import S3Objects

database = Database("postgresql://renotrace_test:local-test-only@127.0.0.1:55432/renotrace_test")
database.migrate()
store = S3Objects(
    "http://127.0.0.1:59000", "renotrace-local", "local-object-test-only", "guest-originals"
)
for attempt in range(30):
    try:
        buckets = store.client.list_buckets()["Buckets"]
        break
    except (EndpointConnectionError, ConnectionClosedError, ReadTimeoutError):
        if attempt == 29:
            raise
        time.sleep(1)
if not any(bucket["Name"] == store.bucket for bucket in buckets):
    store.client.create_bucket(Bucket=store.bucket)
print("Local guest schema and private bucket are ready")
