"""Start actual API and built Next.js servers; verify HTTP responses; stop both."""

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_http(process, url):
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Server exited early with {process.returncode}: {url}")
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                assert response.status == 200
                return response.read().decode("utf-8")
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.2)
    raise RuntimeError(f"Server startup timed out: {url}")


def main():
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("Node is required; install the version in .node-version")
    api_port, web_port = free_port(), free_port()
    while web_port == api_port:
        web_port = free_port()
    commands = [
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(api_port),
        ],
        [
            node,
            str(ROOT / "node_modules/next/dist/bin/next"),
            "start",
            "apps/web",
            "--hostname",
            "127.0.0.1",
            "--port",
            str(web_port),
        ],
    ]
    processes = []
    with tempfile.TemporaryFile(mode="w+b") as log:
        try:
            for command in commands:
                processes.append(
                    subprocess.Popen(
                        command,
                        cwd=ROOT,
                        stdout=log,
                        stderr=log,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                    )
                )
            health = wait_http(processes[0], f"http://127.0.0.1:{api_port}/healthz")
            assert json.loads(health) == {"status": "ok", "service": "renotrace-api"}
            html = wait_http(processes[1], f"http://127.0.0.1:{web_port}/")
            assert "RenoTrace" in html and "Coming soon." in html and '<html lang="en"' in html
            print(
                "PASS: real FastAPI /healthz and built Next.js page "
                "return expected HTTP 200 content."
            )
        except Exception:
            log.seek(0)
            print(log.read().decode("utf-8", errors="replace"), file=sys.stderr)
            raise
        finally:
            for process in processes:
                if process.poll() is None:
                    process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)


if __name__ == "__main__":
    main()
