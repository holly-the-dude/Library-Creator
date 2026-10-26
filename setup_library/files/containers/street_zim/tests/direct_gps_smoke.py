"""Run inside the image, with GPS_MODE=serial and no device passed through."""
import json
import subprocess
import sys
import time
from urllib.request import urlopen

process = subprocess.Popen([sys.executable, '/opt/street_zim/server.py'])
try:
    deadline = time.monotonic() + 15
    while True:
        try:
            with urlopen('http://127.0.0.1:8093/health', timeout=2) as response:
                status = json.load(response)
            break
        except OSError:
            if process.poll() is not None or time.monotonic() >= deadline:
                raise
            time.sleep(0.2)
    assert status['ready'] and status['gps_mode'] == 'serial'
    with urlopen('http://127.0.0.1:8093/api/gps', timeout=3) as response:
        gps = json.load(response)
    assert gps['fix_valid'] is False and gps['status'] == 'no_device', gps
    print('PASS: direct GPS mode starts without hardware and reports no_device; empty reader stays healthy.')
finally:
    process.terminate()
    assert process.wait(timeout=10) == 0
