"""Discover downloadable Library content and probe source-host connectivity.

This module is imported by app.py, not run as a command. It uses HTTPS and
standard-library HTML/JSON parsers to normalize PMTiles, OSM PBF, ZIM, and category ZIP
metadata into catalog dictionaries. Discovery fetches listings and small Git
LFS pointers, never full content archives. See docs/DEVELOPMENT.md for the
source-specific assumptions and docs/API.md for the catalog row schema.
"""

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from pathlib import PurePosixPath
from urllib.parse import unquote, urljoin, urlsplit
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

MAPS_REPO = "Pendia/Project-N.O.M.A.D-Maps"
MAPS_API = f"https://api.github.com/repos/{MAPS_REPO}/contents/pmtiles"
WIKI_URL = "https://dumps.wikimedia.org/kiwix/zim/wikipedia/"
ZIM_CATALOG_URL = "https://library.kiwix.org/catalog/v2/entries"
STREETZIM_URL = "https://streetzim.web.app/"
ATOM = "{http://www.w3.org/2005/Atom}"
METALINK = "{urn:ietf:params:xml:ns:metalink}"
KIWIX_DOWNLOAD_HOSTS = {"download.kiwix.org", "lb.download.kiwix.org", "lbo.download.kiwix.org"}
ROUTING_URL = "https://download.geofabrik.de/north-america/us.html"
SURVIVOR_URL = "https://www.survivorlibrary.com/index.php/main-category-index/"
SOURCES = {
    "maps": {"name": "Regional maps", "url": f"https://github.com/{MAPS_REPO}"},
    "routing": {"name": "Routing · US regions", "url": ROUTING_URL},
    "wiki": {"name": "Kiwix ZIM Library", "url": "https://library.kiwix.org/"},
    "streetzim": {"name": "StreetZim maps", "url": STREETZIM_URL},
    "survivor": {"name": "Survivor Library", "url": SURVIVOR_URL},
}
DESTINATIONS = {"routing": "maps/osm", "maps": "maps/pmtiles", "wiki": "wiki",
                "streetzim": "wiki", "survivor": "library"}
USER_AGENT = "Library-Data-Download/1.0"


def internet_available():
    """Return whether any configured source host responds over HTTPS.

    Try HEAD requests sequentially with a five-second timeout each. HTTP error
    responses still establish connectivity; DNS/TLS/connection failures do not.
    Reject responses redirected to another hostname. This is a reachability
    heuristic, not proof that every catalog or individual file is available.
    """
    for url in ("https://github.com/", "https://library.kiwix.org/",
                "https://www.survivorlibrary.com/", "https://download.geofabrik.de/", STREETZIM_URL):
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


def is_kiwix_zim_url(url):
    """Identify direct ZIM URLs for which Kiwix provides Metalink metadata."""
    parsed = urlsplit(url)
    return (parsed.scheme == "https" and parsed.netloc in KIWIX_DOWNLOAD_HOSTS
            and not parsed.query and not parsed.fragment
            and bool(re.fullmatch(r"/zim/[\w-]+/[^/]+\.zim", parsed.path)))


def resolve_zim_metadata(row):
    """Replace Kiwix's rounded catalog size with exact Metalink size/SHA-256.

    Resolve only the queued file, before transfer or resume, rather than fetching
    thousands of metadata files during discovery. Recognize old cached Kiwix
    URLs too: those rows predate the size_is_approximate flag. Update the worker's
    row only after all metadata validates; never follow Metalink mirror URLs.
    """
    if row["source"] == "streetzim":
        resolve_streetzim_metadata(row)
        return
    if row["source"] != "wiki" or not is_kiwix_zim_url(row["url"]):
        return
    root = ET.fromstring(fetch(row["url"] + ".meta4"))
    if root.tag != METALINK + "metalink":
        raise ValueError("Expected Kiwix Metalink download metadata")
    files = [file for file in root.findall(METALINK + "file")
             if file.get("name") == row["filename"]]
    if len(files) != 1:
        raise ValueError("Kiwix download metadata does not identify the selected file")
    file = files[0]
    try:
        size = int(file.findtext(METALINK + "size", default=""))
    except ValueError:
        raise ValueError("Kiwix download metadata has an invalid file size") from None
    digest = file.findtext(METALINK + "hash[@type='sha-256']", default="").strip().lower()
    if size <= 0 or not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise ValueError("Kiwix download metadata requires a positive size and SHA-256")
    row.update(size=size, sha256=digest, size_is_approximate=False)


def streetzim_location(url):
    """Accept direct archive downloads advertised by StreetZim, not previews."""
    parsed = urlsplit(url)
    match = re.fullmatch(r"/download/(streetzim-[a-z0-9-]+)/([^/]+\.zim)", parsed.path)
    if (parsed.scheme != "https" or parsed.netloc != "archive.org" or
            parsed.query or parsed.fragment or not match):
        raise ValueError("Invalid StreetZim archive URL")
    return match[1], safe_name(unquote(match[2]))


class StreetZimCards(HTMLParser):
    """Read regional cards without mistaking preview/torrent links for ZIMs."""
    fields = {"map-card-title": "title", "map-card-desc": "description",
              "map-card-size": "size", "map-badge": "features"}

    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.cards, self.stack, self.card = [], [], None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get("class", "").split()
        if self.card is None:
            if tag != "div" or "map-card" not in classes:
                return
            self.card = {"url": "", "date": ""}
        if tag == "a":
            url = attrs.get("href", "")
            try:
                streetzim_location(url)
                self.card["url"] = url
            except ValueError:
                pass
        if tag == "time":
            self.card["date"] = attrs.get("datetime", "")[:10]
        if tag not in {"br", "hr", "img", "input", "meta", "link", "source", "wbr"}:
            field = next((self.fields[c] for c in classes if c in self.fields), None)
            self.stack.append((tag, field))

    def handle_data(self, data):
        if self.card is not None:
            for _, field in self.stack:
                if field:
                    self.card[field] = self.card.get(field, "") + data + " "

    def handle_endtag(self, tag):
        if self.card is None:
            return
        index = next((i for i in range(len(self.stack) - 1, -1, -1)
                      if self.stack[i][0] == tag), None)
        if index is None:
            return
        del self.stack[index:]
        if not self.stack:
            self.cards.append(self.card)
            self.card = None


def parse_streetzim_catalog(html):
    rows = {}
    for card in StreetZimCards(html).cards:
        if not card["url"]:
            continue
        size = None
        match = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)\s*(KB|MB|GB|TB)\s*", card.get("size", ""))
        if match:
            size = int(float(match[1]) * 1024 ** (1 + ["KB", "MB", "GB", "TB"].index(match[2])))
        row = item("streetzim", card["url"], size,
                   title=" ".join(card.get("title", "").split()) or None)
        row.update(description=" ".join(card.get("description", "").split()),
                   features=" ".join(card.get("features", "").split()),
                   date=card["date"], category="maps", size_is_approximate=True)
        rows[row["url"]] = row
    return list(rows.values())


def resolve_streetzim_metadata(row):
    """Resolve exact size and MD5 for the selected archive before transferring."""
    identifier, filename = streetzim_location(row["url"])
    if row["filename"] != filename:
        raise ValueError("StreetZim filename does not match its download URL")
    metadata = json.loads(fetch(f"https://archive.org/metadata/{identifier}"))
    matches = [file for file in metadata.get("files", []) if file.get("name") == filename]
    if len(matches) != 1:
        raise ValueError("StreetZim download metadata does not identify the selected archive")
    file = matches[0]
    try:
        size = int(file.get("size", ""))
    except (ValueError, TypeError):
        raise ValueError("StreetZim metadata has an invalid file size") from None
    digest = str(file.get("md5", "")).lower()
    if size <= 0 or not re.fullmatch(r"[a-f0-9]{32}", digest):
        raise ValueError("StreetZim metadata requires a positive size and MD5")
    row.update(size=size, md5=digest, sha256=None, size_is_approximate=False)


def parse_zim_catalog(xml):
    """Read one Kiwix OPDS page, preserving advertised sizes and metadata.

    Acquisition links may point at Metalink metadata; strip only its suffix to
    request the actual ZIM. OPDS lengths are bytes but may be rounded to KiB;
    resolve_zim_metadata obtains exact sizes before downloading. Accept only
    Kiwix HTTPS download hosts and paths.
    Return rows, raw entry count, total results, and page offset for pagination.
    """
    root = ET.fromstring(xml)
    if root.tag != ATOM + "feed":
        raise ValueError("Expected a Kiwix OPDS feed")
    entries = root.findall(ATOM + "entry")
    rows = []
    for entry in entries:
        def value(name):
            return entry.findtext(ATOM + name, default="").strip()

        for link in entry.findall(ATOM + "link"):
            if link.get("type") != "application/x-zim":
                continue
            parsed = urlsplit(link.get("href", ""))
            path = parsed.path.removesuffix(".meta4")
            url = parsed._replace(path=path).geturl()
            if not is_kiwix_zim_url(url):
                continue
            try:
                size = int(link.get("length", ""))
                if size <= 0:
                    continue
                row = item("wiki", url, size,
                           title=value("title") or None)
            except ValueError:
                continue
            tags = value("tags").split(";")
            category = (value("category") or next(
                (tag.split(":", 1)[1] for tag in tags if tag.startswith("_category:")), "")
                or path.split("/")[2])
            # The download directory identifies map archives even when OPDS
            # leaves category blank (as current map entries do).
            if path.split("/")[2] == "maps":
                category = "maps"
            row.update(size_is_approximate=True, description=value("summary"),
                       languages=[code.strip() for code in value("language").split(",") if code.strip()],
                       category=category.lower(), date=value("updated")[:10],
                       flavour=value("flavour"), tags=tags)
            rows.append(row)
            break
    total = int(root.findtext(ATOM + "totalResults", default="-1"))
    start = int(root.findtext(ATOM + "startIndex", default="-1"))
    if total < 0 or start < 0:
        raise ValueError("Missing Kiwix catalog pagination metadata")
    return rows, len(entries), total, start


def discover_zims(publish):
    """Publish bounded OPDS pages; retain cached rows if a later page fails."""
    start = 0
    for _ in range(100):
        rows, count, total, offset = parse_zim_catalog(
            fetch(f"{ZIM_CATALOG_URL}?count=500&start={start}"))
        if offset != start or (not count and start < total):
            raise ValueError("Kiwix catalog pagination did not advance")
        publish(rows)
        start += count
        if start >= total:
            return ""
    raise ValueError("Kiwix catalog exceeds the discovery page limit")


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


def routing_links(html):
    """Return only current US regional PBF URLs on Geofabrik's HTTPS host."""
    urls = set()
    for link in Links(html).links:
        parsed = urlsplit(urljoin(ROUTING_URL, link["href"]))
        if (parsed.scheme == "https" and parsed.netloc == "download.geofabrik.de"
                and not parsed.query and not parsed.fragment
                and re.fullmatch(r"/north-america/us/[a-z][a-z-]*-latest\.osm\.pbf", parsed.path)):
            urls.add(parsed.geturl())
    return sorted(urls)


def routing_item(url):
    """Read exact byte length and upstream MD5 without downloading the PBF."""
    request = Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=30) as response:
        size = int(response.headers["Content-Length"])
    if size <= 0:
        raise ValueError("Invalid routing file size")
    checksum = fetch(url + ".md5", limit=1024).split()
    if not checksum or not re.fullmatch(r"[a-fA-F0-9]{32}", checksum[0]):
        raise ValueError("Invalid routing MD5 metadata")
    title = PurePosixPath(urlsplit(url).path).name.removesuffix("-latest.osm.pbf").replace("-", " ").title()
    row = item("routing", url, size, title=title + " · routing")
    row["md5"] = checksum[0].lower()
    return row


def discover(source, publish):
    """Fetch a source catalog and pass each available row batch to publish.

    Args:
        source: One of maps, routing, wiki, streetzim, or survivor.
        publish: Callback receiving a list of dictionaries from item().

    Return an empty string on success or a warning for failed child listings.
    Initial listing/network/parser failures propagate to Application. Maps and
    Survivor category scans use at most four parallel requests per source; the
    callback is invoked by this function's caller thread as futures complete.
    """
    errors = []
    if source == "wiki":
        return discover_zims(publish)
    if source == "streetzim":
        rows = parse_streetzim_catalog(fetch(STREETZIM_URL))
        if not rows:
            raise ValueError("No StreetZim archives found in the catalog")
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
    elif source == "routing":
        work = routing_links(fetch(ROUTING_URL))
        if not work:
            raise ValueError("No US regional routing extracts found")
        fn = lambda url: [routing_item(url)]
    elif source == "survivor":
        categories = category_links(fetch(SURVIVOR_URL))
        if not categories:
            raise ValueError("No Survivor Library categories found")
        work = list(categories.items())
        fn = lambda pair: parse_survivor(fetch(pair[0]), pair[0], pair[1])
    else:
        raise ValueError("Unknown source")
    with ThreadPoolExecutor(max_workers=4) as pool:
        pending = [pool.submit(fn, entry) for entry in work]
        for future in as_completed(pending):
            try:
                publish(future.result())
            except Exception as exc:
                errors.append(str(exc))
    return f"{len(errors)} listing(s) unavailable: {errors[0]}" if errors else ""
