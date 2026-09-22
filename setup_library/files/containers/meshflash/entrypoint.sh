#!/bin/sh
set -eu
umask 077
# A disconnect only detaches the client, leaving flashing running in tmux.
tmux -L meshflash -f /opt/meshflash/tmux.conf new-session -d -s flash \
    -x 100 -y 30 'exec python3 /opt/meshflash/flasher.py'
set -- ttyd --writable --check-origin --max-clients 1 --port "${PORT:-8086}"
if [ -n "${TTYD_CREDENTIAL:-}" ]; then
    set -- "$@" --credential "$TTYD_CREDENTIAL"
else
    echo 'meshflash: no browser password configured; use only on a trusted LAN.' >&2
fi
exec "$@" /usr/local/bin/meshflash
