#!/bin/bash
# Supervise the public proxy and the loopback-only Calibre-Web backend.
set -euo pipefail

if [ ! -f /root/.calibre-web/app.db ]; then
    python3 /usr/local/bin/initialize-calibre-web.py
fi
python3 /usr/local/bin/configure-calibre-web.py
nginx -t

cps_pid=
nginx_pid=
stop_services() {
    trap '' TERM INT
    [ -z "$nginx_pid" ] || kill -QUIT "$nginx_pid" 2>/dev/null || true
    [ -z "$cps_pid" ] || kill -TERM "$cps_pid" 2>/dev/null || true
    # Bound shutdown even if cps receives TERM while it is still starting.
    for i in $(seq 1 10); do
        if ! kill -0 "$cps_pid" 2>/dev/null && ! kill -0 "$nginx_pid" 2>/dev/null; then
            break
        fi
        sleep 1
    done
    [ -z "$cps_pid" ] || kill -KILL "$cps_pid" 2>/dev/null || true
    [ -z "$nginx_pid" ] || kill -KILL "$nginx_pid" 2>/dev/null || true
    wait || true
}
trap 'stop_services; exit 0' TERM INT

/usr/local/bin/cps -i 127.0.0.1 &
cps_pid=$!
nginx -g 'daemon off;' &
nginx_pid=$!

status=0
wait -n "$cps_pid" "$nginx_pid" || status=$?
echo "A Calibre-Web service exited (status $status); stopping container."
stop_services
if [ "$status" -eq 0 ]; then status=1; fi
exit "$status"
