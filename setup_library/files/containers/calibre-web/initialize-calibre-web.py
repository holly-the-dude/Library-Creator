#!/usr/bin/env python3
"""Create Calibre-Web's database without leaving its temporary server running."""

import sqlite3
import subprocess
import time
import urllib.error
import urllib.request


def initialize():
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    process = subprocess.Popen(["/usr/local/bin/cps", "-i", "127.0.0.1"])
    try:
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(
                    f"Calibre-Web exited during initialization: {process.returncode}"
                )
            try:
                # A database file alone does not mean startup has finished.
                # Wait until the server can handle requests before sending SIGTERM.
                with opener.open("http://127.0.0.1:8083/", timeout=2):
                    pass
                with sqlite3.connect(
                    "file:/root/.calibre-web/app.db?mode=ro", uri=True
                ) as connection:
                    if connection.execute("SELECT 1 FROM settings").fetchone():
                        return
            except (urllib.error.URLError, TimeoutError, sqlite3.Error):
                pass
            time.sleep(1)
        raise RuntimeError("Calibre-Web was not ready within 180 seconds")
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                print("Calibre-Web did not stop within 10 seconds; forcing shutdown", flush=True)
                process.kill()
                process.wait(timeout=10)


if __name__ == "__main__":
    initialize()
