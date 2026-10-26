#!/usr/bin/env python3
"""Supervise a private Kiwix reader, nginx and optional serial GPS reader."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent


def gps_upstream(environ):
    mode = environ.get("GPS_MODE", "relay")
    if mode == "serial":
        return mode, "http://127.0.0.1:8765"
    if mode != "relay":
        raise ValueError("GPS_MODE must be relay or serial")
    value = environ.get("GPS_UPSTREAM", "http://10.88.0.212:8080").rstrip("/")
    url = urlsplit(value)
    # This value is inserted into nginx configuration: accept only an origin.
    if (url.scheme != "http" or not url.hostname or url.username or url.password
            or url.path or url.query or url.fragment
            or any(c in value for c in '{};$\\"\'\n\r\t ')):
        raise ValueError("GPS_UPSTREAM must be an http://host:port origin")
    _ = url.port  # Also validate port syntax/range.
    return mode, value


def make_library(data_dir, library):
    # macOS writes AppleDouble metadata beside files on USB drives. These
    # sidecars retain the .zim suffix but are not archives (even if orphaned).
    archives = sorted(p for p in data_dir.glob("*.zim")
                      if not p.name.startswith("._") and p.is_file())
    library.write_text('<?xml version="1.0" encoding="UTF-8"?>\n'
                       '<library version="20110515"></library>\n')
    for archive in archives:
        subprocess.run(["kiwix-manage", str(library), "add", str(archive)], check=True)
    return archives


def make_status_server(state, port=8766):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = urlsplit(self.path).path
            if path not in ("/health", "/api/status"):
                self.send_error(404)
                return
            ready = all(child.poll() is None for child in state["children"])
            try:
                with urlopen("http://127.0.0.1:8094/maps/", timeout=2) as response:
                    ready = ready and response.status == 200
            except OSError:
                ready = False
            payload = {k: v for k, v in state.items() if k != "children"}
            payload["ready"] = ready
            body = json.dumps(payload).encode()
            self.send_response(503 if path == "/health" and not ready else 200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main():
    mode, upstream = gps_upstream(os.environ)
    work = Path("/tmp/street_zim")
    work.mkdir(exist_ok=True)
    config = (ROOT / "nginx.conf.in").read_text().replace("__GPS_UPSTREAM__", upstream)
    (work / "nginx.conf").write_text(config)
    subprocess.run(["nginx", "-t", "-c", str(work / "nginx.conf")], check=True)
    archives = make_library(Path("/data"), work / "library.xml")
    children = []
    stop = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stop.set())
    state = {"gps_mode": mode, "gps_upstream": upstream,
             "archives": [p.name for p in archives], "children": children}
    server = make_status_server(state)
    result = 0
    try:
        children.append(subprocess.Popen([
            "kiwix-serve", "--address=127.0.0.1", "--port=8094",
            "--urlRootLocation=/maps", "--nosearchbar", "--library", str(work / "library.xml")]))
        if mode == "serial":
            children.append(subprocess.Popen([sys.executable, str(ROOT / "gps/gps_service.py")]))
        children.append(subprocess.Popen(["nginx", "-c", str(work / "nginx.conf"), "-g", "daemon off;"]))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        print(f"StreetZim :8093 — {len(archives)} archive(s), GPS mode={mode}", flush=True)
        while not stop.wait(0.5):
            if any(child.poll() is not None for child in children):
                print("A child service exited; stopping the container.", file=sys.stderr)
                result = 1
                break
    finally:
        # Never leave an unhealthy half-running container or orphaned reader.
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        server.server_close()
    return result


if __name__ == "__main__":
    sys.exit(main())
