#!/usr/bin/env python3
"""Configure the appliance's local proxy to sign visitors in as admin."""

import sqlite3


def configure(path="/root/.calibre-web/app.db"):
    with sqlite3.connect(f"file:{path}?mode=rw", uri=True) as connection:
        admin = connection.execute(
            "SELECT role FROM user WHERE lower(name) = 'admin'"
        ).fetchone()
        if not admin or not admin[0] & 1:
            raise RuntimeError("Automatic login requires an existing admin account with administrator permissions")
        cursor = connection.execute("""
            UPDATE settings SET
                config_calibre_dir = COALESCE(NULLIF(config_calibre_dir, ''), '/books'),
                config_port = 8084,
                config_external_port = 8083,
                config_anonbrowse = 0,
                config_login_type = 0,
                config_allow_reverse_proxy_header_login = 1,
                config_reverse_proxy_login_header_name = 'X-Calibre-User',
                config_reverse_proxy_trusted_ips = '127.0.0.1/32',
                config_reverse_proxy_use_shared_secret = 0
        """)
        if cursor.rowcount != 1:
            raise RuntimeError("Expected one Calibre-Web settings row")
    print("Calibre-Web: automatic admin login through the local proxy enabled", flush=True)


if __name__ == "__main__":
    configure()
