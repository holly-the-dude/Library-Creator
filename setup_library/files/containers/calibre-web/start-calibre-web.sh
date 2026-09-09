#!/bin/bash
# Startup script for Calibre-Web
# Ensures the library path is set to /books before starting the server.
# This avoids the "initial setup" prompt on first run.

APP_DB="/root/.calibre-web/app.db"

# Wait for app.db to be created on first launch, or pre-configure it
if [ ! -f "$APP_DB" ]; then
    # Start cps briefly to generate the default app.db, then stop it
    /usr/local/bin/cps &
    CPS_PID=$!
    # Wait for app.db to appear
    for i in $(seq 1 30); do
        [ -f "$APP_DB" ] && break
        sleep 1
    done
    kill $CPS_PID 2>/dev/null
    wait $CPS_PID 2>/dev/null
    sleep 1
fi

# Set the calibre library path if not already configured
if [ -f "$APP_DB" ]; then
    python3 -c "
import sqlite3
conn = sqlite3.connect('$APP_DB')
c = conn.cursor()
c.execute('SELECT config_calibre_dir FROM settings')
row = c.fetchone()
if row and (row[0] is None or row[0] == ''):
    c.execute('UPDATE settings SET config_calibre_dir = \"/books\"')
    conn.commit()
    print('Calibre-Web: Library path set to /books')
else:
    print('Calibre-Web: Library path already configured as', row[0] if row else 'N/A')
conn.close()
"
fi

# Now start cps for real
exec /usr/local/bin/cps
