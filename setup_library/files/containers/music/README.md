# Music Container

The music container runs [LMS (Lightweight Music Server)](https://github.com/epoupon/lms) to provide a web-based music streaming interface. It serves audio files from the library and supports the Subsonic API for mobile clients.

## File Structure

```
music/
├── Containerfile          # Container build instructions
├── lms.conf               # LMS configuration (http-headers auth, reverse proxy)
├── pam_lms                # PAM configuration for lms
├── music_default_data.tar # Pre-configured database with "music" user
├── approot/
│   ├── login.xml          # Customized login page (pre-filled credentials)
│   └── messages.xml       # Customized messages (welcome text shows credentials)
└── README.md
```

## Building the Container

```bash
podman build -t localhost/music:latest .
```

This pulls `docker.io/epoupon/lms:latest` (Alpine-based) and applies customizations.

## Running the Container

```bash
podman run -d \
    --name music \
    --ip 10.88.0.210 \
    -p 9099:5082 \
    -v /Library/music/:/music/:ro \
    -v /Library/.music_data:/var/lms \
    localhost/music:latest
```

- **IP**: 10.88.0.210 (static on the podman network)
- **Port 5082**: LMS web interface (mapped to 9099 externally)
- **Volume `/music`**: Music files (read-only)
- **Volume `/var/lms`**: Persistent data (database, cache, config)

## Initial Setup

On first deployment, extract the default data tar to create the pre-configured database:

```bash
tar -xf music_default_data.tar -C /
```

This creates `/Library/.music_data/` containing:
- `lms.db` — SQLite database with pre-configured `music` user (admin)
- `wt_config.xml` — Wt framework config (reverse proxy enabled)
- `cache/` — empty cache directory

## Authentication

The container is configured for **http-headers authentication**. When accessed through the webserver's nginx reverse proxy at `http://10.1.1.1/music`, the `X-Forwarded-User: music` header is injected automatically — **no login page is shown**.

For direct access at `http://10.1.1.1:9099`, the login page appears with pre-filled credentials:
- **Username**: `music`
- **Password**: `music`

### How auto-login works

1. User visits `http://10.1.1.1/music`
2. Webserver nginx proxies the request to the music container
3. Nginx injects `X-Forwarded-User: music` header
4. LMS reads the header and authenticates as the `music` user
5. Music player loads directly — no login required

## Configuration

Key settings in `lms.conf`:

| Setting | Value | Purpose |
|---------|-------|---------|
| `authentication-backend` | `http-headers` | Auto-login via reverse proxy header |
| `http-headers-login-field` | `X-Forwarded-User` | Header field containing the username |
| `behind-reverse-proxy` | `true` | Trust proxy headers for real client IP |
| `deploy-path` | `/music` | URL path when accessed via proxy |
| `listen-port` | `5082` | Internal HTTP port |
| `working-dir` | `/var/lms/` | Database and cache storage |

## Ports Reference

| Port | Service |
|------|---------|
| 5082 (internal) | LMS web interface |
| 9099 (external) | Direct access (with login page) |

## Network

| Address | Purpose |
|---------|---------|
| 10.88.0.210 | Music container on podman network |
| 10.1.1.1/music | Auto-login access via webserver proxy |
| 10.1.1.1:9099 | Direct access (shows login form) |

## Subsonic API

LMS exposes a Subsonic-compatible API for mobile music apps (DSub, Ultrasonic, etc.):
- **URL**: `http://10.1.1.1:9099`
- **Username**: `music`
- **Password**: `music`

## Music Library

The host volume `/Library/music/` is mounted read-only at `/music/` inside the container. Place audio files here and trigger a scan from the LMS admin interface.

Supported formats include MP3, FLAC, OGG, Opus, AAC, and others supported by ffmpeg.

## Troubleshooting

- **Login page shows instead of auto-login** — You're accessing via port 9099 directly. Use `http://10.1.1.1/music` to go through the proxy.
- **"User not found" error via proxy** — The `music` user must exist in the LMS database. Re-extract `music_default_data.tar` to `/`.
- **No music showing** — Trigger a scan from the admin panel (Settings > Scanner > Scan now). Ensure `/Library/music/` has audio files.
- **Container won't start** — Check logs with `podman logs music`. Common issue is `/Library/.music_data` not existing (extract the default data tar first).
- **Proxy returns 502** — The music container may not be running or hasn't finished starting. LMS takes a few seconds to initialize.
