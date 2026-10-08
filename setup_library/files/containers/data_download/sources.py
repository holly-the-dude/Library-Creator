"""Discover downloadable Library content and probe source-host connectivity.

This module is imported by app.py, not run as a command. It uses HTTPS and
standard-library HTML/JSON parsers to normalize PMTiles, ZIM, and category ZIP
metadata into catalog dictionaries. Discovery fetches listings and small Git
LFS pointers, never full content archives. See docs/DEVELOPMENT.md for the
source-specific assumptions and docs/API.md for the catalog row schema.
"""

import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from pathlib import PurePosixPath
from urllib.parse import unquote, urljoin, urlsplit
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

MAPS_REPO = "Pendia/Project-N.O.M.A.D-Maps"
MAPS_API = f"https://api.github.com/repos/{MAPS_REPO}/contents/pmtiles"
WIKI_URL = "https://dumps.wikimedia.org/kiwix/zim/wikipedia/"
SURVIVOR_URL = "https://www.survivorlibrary.com/index.php/main-category-index/"
SOURCES = {
    "maps": {"name": "Regional maps", "url": f"https://github.com/{MAPS_REPO}"},
    "wiki": {"name": "Wikipedia", "url": WIKI_URL},
    "survivor": {"name": "Survivor Library", "url": SURVIVOR_URL},
}
DESTINATIONS = {"maps": "maps/pmtiles", "wiki": "wiki", "survivor": "library"}
USER_AGENT = "Library-Data-Download/1.0"


def internet_available():
    """Return whether any configured source host responds over HTTPS.

    Try HEAD requests sequentially with a five-second timeout each. HTTP error
    responses still establish connectivity; DNS/TLS/connection failures do not.
    Reject responses redirected to another hostname. This is a reachability
    heuristic, not proof that every catalog or individual file is available.
    """
    for url in ("https://github.com/", "https://dumps.wikimedia.org/",
                "https://www.survivorlibrary.com/"):
        request = Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
        try:
            with urlopen(request, timeout=5) as response:
                if urlsplit(response.geturl()).hostname == urlsplit(url).hostname:
                    return True
        except HTTPError as exc:
            # Rate limits and server errors still prove internet connectivity.
            reachable = urlsplit(exc.geturl()).hostname == urlsplit(url).hostname
            exc.close()
            if reachable:
                return True
        except (URLError, OSError):
            continue
    return False


def open_url(url, headers=None):
    """Open an HTTPS GET with a 30-second timeout and caller-supplied headers.

    Request identity encoding so byte counts/ranges match stored content.
    The caller closes the returned response, normally with a context manager.
    urllib follows redirects and propagates network/HTTP errors to the caller.
    """
    if urlsplit(url).scheme != "https":
        raise ValueError("Only HTTPS source URLs are supported")
    request = Request(url, headers={"User-Agent": USER_AGENT,
                                   "Accept-Encoding": "identity", **(headers or {})})
    return urlopen(request, timeout=30)


def fetch(url, limit=8 * 1024 * 1024):
    """Fetch bounded metadata as UTF-8 text; raise ValueError above limit bytes."""
    with open_url(url) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Source listing exceeds the discovery limit")
    return data.decode("utf-8", errors="replace")


class Links(HTMLParser):
    """Collect href/text pairs, tolerating malformed source-page anchors.

    Text continues after </a> until the next anchor. This deliberately captures
    directory-listing timestamps and byte counts that follow a filename link.
    This parser is for discovery, not a general-purpose DOM representation.
    """

    def __init__(self, html):
        """Parse supplied HTML immediately into the links list."""
        super().__init__(convert_charrefs=True)
        self.links = []
        self.current = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        """Start a new record for each anchor, with an empty href if missing."""
        if tag == "a":
            self.current = {"href": dict(attrs).get("href", ""), "text": ""}
            self.links.append(self.current)

    def handle_data(self, data):
        """Append decoded text to the most recently encountered anchor."""
        if self.current is not None:
            self.current["text"] += data


def safe_name(name):
    """Return a filename or reject hidden names, separators, and control bytes."""
    if (not name or name in {".", ".."} or name.startswith(".")
            or any(c in name for c in '/\\\x00')
            or any(ord(c) < 32 for c in name)):
        raise ValueError("Unsafe source filename")
    return name


def item(source, url, size=None, title=None, sha256=None):
    """Build a catalog row with a stable source/URL ID and relative destination.

    Size is an exact byte count or None. SHA-256 is optional source metadata.
    Survivor ZIP filenames become category directories by dropping .zip.
    The ID identifies a URL, not a specific version of its remote contents.
    """
    name = safe_name(unquote(PurePosixPath(urlsplit(url).path).name))
    return {"id": hashlib.sha256(f"{source}:{url}".encode()).hexdigest()[:24],
            "source": source, "url": url, "filename": name,
            "title": title or name, "size": size, "sha256": sha256,
            "destination": DESTINATIONS[source] + "/" +
            (name[:-4] if source == "survivor" else name)}


def parse_wiki(html):
    """Return ZIM rows from the configured directory, with exact sizes if parsed."""
    result = []
    for link in Links(html).links:
        url = urljoin(WIKI_URL, link["href"])
        if not url.startswith(WIKI_URL) or not urlsplit(url).path.endswith(".zim"):
            continue
        # nginx listings end each row in an exact byte count (not rounded MB).
        match = re.search(r"\d{2}:\d{2}\s+(\d+)\s*$", link["text"])
        result.append(item("wiki", url, int(match[1]) if match else None))
    return result


def category_links(html):
    """Map recognized Survivor Library category-page URLs to readable titles."""
    result = {}
    for link in Links(html).links:
        url = urljoin(SURVIVOR_URL, link["href"])
        parsed = urlsplit(url)
        if (parsed.hostname in {"www.survivorlibrary.com", "survivorlibrary.com"}
                and re.fullmatch(r"/index.php/library-[\w-]+/?", parsed.path)):
            result[url] = parsed.path.rstrip("/").split("library-", 1)[1].replace("_", " ").title()
    return result


def parse_survivor(html, page, title):
    """Return unique same-site ZIP links from a category, excluding PDF links.

    Resolve relative links against page, normalize downloads to HTTPS, and leave
    size unknown rather than treating rounded human-readable MB values as exact.
    """
    result = {}
    for link in Links(html).links:
        url = urljoin(page, link["href"])
        parsed = urlsplit(url)
        if (parsed.hostname in {"www.survivorlibrary.com", "survivorlibrary.com"}
                and parsed.path.lower().endswith(".zip")):
            # Some historic pages use http; the site also serves these via TLS.
            url = parsed._replace(scheme="https", fragment="").geturl()
            result[url] = item("survivor", url, title=title)
    return list(result.values())


def map_item(entry):
    """Convert GitHub contents metadata into a downloadable PMTiles row.

    Files reported below 1 KiB are treated as LFS pointers. Resolve their real
    length/SHA-256 and use GitHub's media URL instead of downloading the pointer.
    Larger ordinary Git blobs retain their supplied size and download URL.
    """
    url = entry["download_url"]
    size = entry.get("size")
    digest = None
    # GitHub's contents API reports the size of an LFS POINTER, not the map.
    if size is not None and size < 1024:
        pointer = fetch(url, limit=2048)
        length = re.search(r"^size (\d+)$", pointer, re.M)
        oid = re.search(r"^oid sha256:([a-f0-9]{64})$", pointer, re.M)
        if not pointer.startswith("version https://git-lfs.github.com/spec/v1") or not length or not oid:
            raise ValueError(f"Invalid LFS metadata for {entry['name']}")
        size, digest = int(length[1]), oid[1]
        url = url.replace("https://raw.githubusercontent.com/",
                          "https://media.githubusercontent.com/media/", 1)
    return item("maps", url, size, sha256=digest)


def discover(source, publish):
    """Fetch a source catalog and pass each available row batch to publish.

    Args:
        source: One of maps, wiki, or survivor, supplied by Application.
        publish: Callback receiving a list of dictionaries from item().

    Return an empty string on success or a warning for failed child listings.
    Initial listing/network/parser failures propagate to Application. Maps and
    Survivor category scans use at most four parallel requests per source; the
    callback is invoked by this function's caller thread as futures complete.
    """
    errors = []
    if source == "wiki":
        rows = parse_wiki(fetch(WIKI_URL))
        if not rows:
            raise ValueError("No ZIM links found in the Wikipedia listing")
        publish(rows)
        return ""
    if source == "maps":
        entries = json.loads(fetch(MAPS_API))
        if not isinstance(entries, list):
            raise ValueError("Unexpected GitHub response")
        work = [e for e in entries if e.get("type") == "file" and e["name"].endswith(".pmtiles")]
        if not work:
            raise ValueError("No PMTiles found in the repository")
        fn = lambda entry: [map_item(entry)]
    else:
        categories = category_links(fetch(SURVIVOR_URL))
        if not categories:
            raise ValueError("No Survivor Library categories found")
        work = list(categories.items())
        fn = lambda pair: parse_survivor(fetch(pair[0]), pair[0], pair[1])
    with ThreadPoolExecutor(max_workers=4) as pool:
        pending = [pool.submit(fn, entry) for entry in work]
        for future in as_completed(pending):
            try:
                publish(future.result())
            except Exception as exc:
                errors.append(str(exc))
    return f"{len(errors)} listing(s) unavailable: {errors[0]}" if errors else ""
