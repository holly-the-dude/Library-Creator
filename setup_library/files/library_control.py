#!/usr/bin/python3
"""Host-only, systemd socket-activated bridge for a fixed restart request.

The root-only Unix socket is shared with the downloader, without exposing the
Podman socket or a network listener. Accept only ``restart\n``; systemd runs the
graceful sequence independently so stopping the downloader cannot interrupt it.
See containers/data_download/docs/RESTART.md for installation and protocol.
"""

import os
import socket
import socketserver
import subprocess


class Handler(socketserver.StreamRequestHandler):
    """Bound request reads and schedule exactly one known host service."""

    def handle(self):
        self.connection.settimeout(5)
        try:
            if self.rfile.readline(128) != b"restart\n":
                self.wfile.write(b"ERROR Invalid request\n")
                return
            subprocess.run(["/usr/bin/systemctl", "--no-block", "start",
                            "library-restart.service"], check=True, timeout=10,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            self.wfile.write(b"OK\n")
        except (OSError, subprocess.SubprocessError):
            self.wfile.write(b"ERROR Could not schedule restart; check host service logs\n")


def main():
    """Serve the listening Unix socket passed by library-control.socket."""
    if (os.environ.get("LISTEN_PID") != str(os.getpid())
            or os.environ.get("LISTEN_FDS") != "1"):
        raise RuntimeError("Start through library-control.socket")
    with socketserver.UnixStreamServer("", Handler, bind_and_activate=False) as server:
        server.socket.close()
        server.socket = socket.socket(fileno=3)
        server.serve_forever()


if __name__ == "__main__":
    main()
