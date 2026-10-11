#!/usr/bin/env python3
"""Bootstrap's Bookworm -> Trixie host upgrade. Exit 10 means reboot required.

Run only on the target Pi as root. Library installation must not proceed after
any nonzero exit. A persisted phase lets a failed APT transaction be retried even
if base-files has already changed /etc/os-release to Trixie.
"""
import fcntl
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import urlparse


STATE_DIR = Path('/var/lib/library-bootstrap')
STATE_FILE = STATE_DIR / 'os-upgrade.json'
APT_DIR = Path('/etc/apt')
BACKUP_DIR = Path('/var/backups')
OS_RELEASE_FILE = Path('/etc/os-release')
BOOT_ID_FILE = Path('/proc/sys/kernel/random/boot_id')
OFFICIAL_HOSTS = {
    'deb.debian.org', 'security.debian.org', 'ftp.debian.org',
    'archive.raspberrypi.org', 'archive.raspberrypi.com',
    'raspbian.raspberrypi.org', 'archive.raspbian.org',
}


def os_release():
    values = {}
    for line in OS_RELEASE_FILE.read_text().splitlines():
        if '=' in line and not line.startswith('#'):
            key, value = line.split('=', 1)
            values[key] = shlex.split(value)[0] if value else ''
    return values


def run(*args, capture=False):
    print('+ ' + shlex.join(args), flush=True)
    return subprocess.run(args, check=True, text=True,
                          stdout=subprocess.PIPE if capture else None).stdout


def apt(*args):
    run('apt-get', '-y', '-o', 'Dpkg::Options::=--force-confold', *args)


def validate_uri(uri):
    parsed = urlparse(uri)
    host = parsed.hostname or ''
    if parsed.scheme not in ('http', 'https') or not (
            host in OFFICIAL_HOSTS or host.endswith('.debian.org')):
        raise ValueError(f'Nonstandard APT source {uri}: disable it before upgrading, then retry.')


def target_suite(suite, resuming):
    allowed = {'bookworm', 'bookworm-updates', 'bookworm-security'}
    if resuming:
        allowed |= {'trixie', 'trixie-updates', 'trixie-security'}
    if suite not in allowed:
        raise ValueError(f'Unsupported APT suite {suite!r}. Use explicit Bookworm sources; '
                         'disable backports, testing, or other releases before upgrading.')
    return suite.replace('bookworm', 'trixie')


def rewrite_sources(text, deb822=False, resuming=False):
    """Change suite fields only; preserve URIs, signing keys, options and comments."""
    count = 0
    if not deb822:
        lines = []
        pattern = re.compile(r'^(\s*deb(?:-src)?\s+(?:\[[^\]]*\]\s+)?)(\S+)(\s+)(\S+)(.*)$')
        for line in text.splitlines(keepends=True):
            if not line.strip() or line.lstrip().startswith('#'):
                lines.append(line)
                continue
            match = pattern.match(line.rstrip('\n'))
            if not match:
                raise ValueError('Unrecognized APT .list entry: ' + line.strip())
            prefix, uri, space, suite, rest = match.groups()
            validate_uri(uri)
            lines.append(prefix + uri + space + target_suite(suite, resuming) + rest +
                         ('\n' if line.endswith('\n') else ''))
            count += 1
        return ''.join(lines), count

    blocks = re.split(r'(\n\s*\n)', text)
    for index in range(0, len(blocks), 2):
        block = blocks[index]
        fields = {}
        field = None
        for line in block.splitlines():
            if not line.strip() or line.lstrip().startswith('#'):
                continue
            if line[0].isspace() and field:
                fields[field] += ' ' + line.strip()
            else:
                field, colon, value = line.partition(':')
                if not colon:
                    raise ValueError('Unrecognized deb822 source entry')
                field = field.lower()
                fields[field] = value.strip()
        if not fields or fields.get('enabled', 'yes').lower() == 'no':
            continue
        if not all(fields.get(key) for key in ('types', 'uris', 'suites')):
            raise ValueError('APT .sources stanza is missing Types, URIs, or Suites')
        for uri in fields['uris'].split():
            validate_uri(uri)
        suites = [target_suite(suite, resuming) for suite in fields['suites'].split()]
        blocks[index] = re.sub(r'^Suites:[^\n]*(?:\n[ \t]+[^\n]*)*',
                               'Suites: ' + ' '.join(suites), block, flags=re.M | re.I)
        count += 1
    return ''.join(blocks), count


def source_plan(resuming=False):
    files = [APT_DIR / 'sources.list']
    files += sorted((APT_DIR / 'sources.list.d').glob('*.list'))
    files += sorted((APT_DIR / 'sources.list.d').glob('*.sources'))
    plan, count = {}, 0
    for path in files:
        if path.exists():
            content, entries = rewrite_sources(path.read_text(), path.suffix == '.sources', resuming)
            plan[path] = content
            count += entries
    if not count:
        raise ValueError('No active supported APT sources found')
    for path in [APT_DIR / 'preferences', *sorted((APT_DIR / 'preferences.d').glob('*'))]:
        if path.is_file() and any(line.strip() and not line.lstrip().startswith('#')
                                  for line in path.read_text().splitlines()):
            raise ValueError(f'APT pinning found in {path}; review and disable pins before upgrading.')
    return plan


def save_state(state):
    temporary = STATE_FILE.with_suffix('.tmp')
    temporary.write_text(json.dumps(state) + '\n')
    temporary.replace(STATE_FILE)


def upgrade():
    release = os_release()
    if release.get('ID') not in ('debian', 'raspbian'):
        raise ValueError('This installer requires Debian or Raspberry Pi OS, not ' + release.get('ID', 'unknown'))
    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else None
    boot_id = BOOT_ID_FILE.read_text().strip()
    if state and state['phase'] == 'complete':
        if state['boot_id'] == boot_id:
            print('Trixie is installed. Reboot before continuing Library installation.')
            return 10
        if release.get('VERSION_CODENAME') != 'trixie':
            raise ValueError('Completed upgrade does not report Trixie; inspect the system before continuing.')
        STATE_FILE.unlink()
        state = None
    if not state and release.get('VERSION_CODENAME') == 'trixie':
        print('OS is already Trixie; no release upgrade needed.')
        return 0
    if not state and release.get('VERSION_CODENAME') != 'bookworm':
        raise ValueError('Automatic host upgrade requires Bookworm (Debian 12). '
                         'Install a 64-bit Trixie image or upgrade older releases to Bookworm first. '
                         'Newer releases are never downgraded.')
    if run('dpkg', '--print-architecture', capture=True).strip() != 'arm64':
        raise ValueError('The Library requires a 64-bit ARM OS; architecture conversion is not supported.')
    if run('apt-mark', 'showhold', capture=True).strip():
        raise ValueError('Held packages found. Resolve the holds before upgrading.')
    plan = source_plan(resuming=bool(state and state['phase'] == 'upgrading'))
    if not state:
        if run('dpkg', '--audit', capture=True).strip():
            raise ValueError('Unconfigured packages found. Repair dpkg before upgrading.')
        backup = Path(tempfile.mkdtemp(prefix='library-os-', dir=BACKUP_DIR))
        shutil.copytree(APT_DIR, backup / 'apt', symlinks=True)
        shutil.copy2(OS_RELEASE_FILE, backup / 'os-release')
        state = {'phase': 'prepared', 'backup': str(backup)}
        save_state(state)
    print('APT configuration backup: ' + state['backup'], flush=True)
    if state['phase'] == 'prepared':
        # Finish the previous release before changing any suites.
        apt('update')
        apt('full-upgrade')
        state['phase'] = 'upgrading'
        save_state(state)
    elif state['phase'] != 'upgrading':
        raise ValueError('Unknown upgrade phase; inspect ' + str(STATE_FILE))
    for path, content in plan.items():
        path.write_text(content)
    apt('update')
    # Also recover an interrupted previous attempt; do not silently skip it just
    # because base-files was upgraded before the rest of the OS.
    run('dpkg', '--force-confold', '--configure', '-a')
    apt('--fix-broken', 'install')
    apt('upgrade', '--without-new-pkgs')
    apt('full-upgrade')
    if run('dpkg', '--audit', capture=True).strip():
        raise ValueError('Package audit failed after upgrade; repair and rerun bootstrap.')
    if os_release().get('VERSION_CODENAME') != 'trixie':
        raise ValueError('APT completed but the OS does not report Trixie. Library installation stopped.')
    state.update(phase='complete', boot_id=boot_id)
    save_state(state)
    print('OS upgrade to Trixie completed. Reboot before continuing Library installation.')
    return 10


def main():
    if os.geteuid() != 0:
        print('OS upgrade must run as root.', file=sys.stderr)
        return 1
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with (STATE_DIR / 'os-upgrade.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return upgrade()
        except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
            print(f'OS preflight failed: {error}\nLibrary installation has not continued. '
                  'Fix the reported issue and rerun bootstrap.', file=sys.stderr)
            return 1


if __name__ == '__main__':
    sys.exit(main())
