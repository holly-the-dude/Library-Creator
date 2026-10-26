"""Write nginx's GPS target; a non-empty GPS_UPSTREAM disables local serial IO."""
import os
from pathlib import Path
from urllib.parse import urlsplit


def gps_proxy_directive(upstream):
    origin = upstream.rstrip('/') if upstream else 'http://127.0.0.1:8765'
    parsed = urlsplit(origin)
    if (parsed.scheme != 'http' or not parsed.hostname or parsed.username or parsed.password
            or parsed.path or parsed.query or parsed.fragment
            or any(c in origin for c in '{};$\\"\'\n\r\t ')):
        raise ValueError('GPS_UPSTREAM must be an http://host:port origin')
    _ = parsed.port
    return f'proxy_pass {origin}/api/gps;\n'


if __name__ == '__main__':
    Path('/etc/nginx/gps-upstream.conf').write_text(gps_proxy_directive(os.environ.get('GPS_UPSTREAM', '')))
