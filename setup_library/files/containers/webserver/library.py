#!/usr/bin/python3
"""
Library Web Interface Generator

Reads configuration from library_setup.yml and:
1. Checks if library file count has changed
2. Discovers which services are running
3. Generates HTML index pages with navigation
4. Configures and starts/reloads nginx
"""

import os
import sys
import requests
from html import escape
from pathlib import Path
from urllib.parse import quote

# PyYAML is required - install with: pip install pyyaml
try:
    import yaml
except ImportError:
    print("ERROR: PyYAML not installed. Install with: pip install pyyaml")
    sys.exit(1)


# =============================================================================
# Configuration Loading
# =============================================================================

# Default configuration used when library_setup.yml is missing
DEFAULT_CONFIG = {
    "webserver": {
        "library_path": "/library/library",
        "web_path": "/library/web",
        "host_ip": "10.1.1.1",
        "nginx": {
            "listen_port": 80,
            "server_names": ["localhost", "library", "library.local", "10.1.1.1"],
        },
        "shutdown_port": 9999,
    },
    "services": [
        {
            "name": "wiki",
            "display_name": "Wiki",
            "internal_ip": "10.88.0.200",
            "internal_port": 6902,
            "external_url": "http://10.1.1.1:6902",
            "check_text": "Kiwix",
            "timeout": 5,
        },
        {
            "name": "music",
            "display_name": "Music",
            "internal_ip": "10.88.0.210",
            "internal_port": 5082,
            "external_url": "http://10.1.1.1:9099",
            "check_text": "Load basic HTML",
            "timeout": 10,
        },
        {
            "name": "ebook",
            "display_name": "eBook Reader",
            "internal_ip": "10.88.0.211",
            "internal_port": 8083,
            "external_url": "http://10.1.1.1:8083",
            "check_text": "Calibre-Web",
            "timeout": 10,
        },
    ],
}


def load_config():
    """
    Load configuration from library_setup.yml.
    Falls back to default configuration if the file is missing or invalid.
    """
    # Config file is in the same directory as this script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, "library_setup.yml")

    if not os.path.exists(config_path):
        print(f"WARNING: {config_path} not found. Using default configuration.")
        return DEFAULT_CONFIG

    try:
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)
        if config is None:
            print("WARNING: library_setup.yml is empty. Using default configuration.")
            return DEFAULT_CONFIG
        print(f"Configuration loaded from {config_path}")
        return config
    except yaml.YAMLError as e:
        print(f"ERROR: Failed to parse library_setup.yml: {e}")
        print("Using default configuration.")
        return DEFAULT_CONFIG


# =============================================================================
# Service Checking
# =============================================================================

def check_service(service):
    """
    Check if a service is running by making an HTTP request and looking
    for the expected check_text in the response.

    Args:
        service: dict with keys: name, display_name, internal_ip,
                 internal_port, external_url, check_text, timeout, and an
                 optional check_path (endpoint path such as "/bridge/status";
                 defaults to the site root).

    Returns:
        HTML string for the nav link if service is up, empty string otherwise.
    """
    internal_ip = service.get("internal_ip", "")
    internal_port = service.get("internal_port", "")
    check_text = service.get("check_text", "")
    # Optional path to verify a specific endpoint (e.g. "/bridge/status").
    # Defaults to the site root for the existing services.
    check_path = service.get("check_path", "")
    timeout = service.get("timeout", 5)
    display_name = service.get("display_name", service.get("name", "Unknown"))
    external_url = service.get("external_url", "")

    # Normalize the optional path so both "bridge/status" and "/bridge/status"
    # work, and an empty/omitted value keeps the previous root-URL behavior.
    if check_path and not check_path.startswith("/"):
        check_path = "/" + check_path
    url = f"http://{internal_ip}:{internal_port}{check_path}"

    try:
        response = requests.get(url, timeout=timeout)
        if check_text in response.content.decode("utf-8"):
            return (
                f'<a href="{escape(external_url, quote=True)}" '
                f'target="_blank" rel="noopener noreferrer">{escape(display_name)}</a>'
            )
    except requests.RequestException:
        pass
    except Exception as e:
        print(f"  Unexpected error checking {display_name}: {e}")

    return ""


def discover_services(services_config):
    """
    Check all configured services and return a list of nav bar HTML snippets
    for those that are running.

    Args:
        services_config: list of service definition dicts from YAML

    Returns:
        list of HTML strings for active services
    """
    active_services = []

    for service in services_config:
        name = service.get("display_name", service.get("name", "unknown"))
        print(f"Checking service: {name}...", end=" ")
        result = check_service(service)
        if result:
            print("UP")
            active_services.append(result)
        else:
            print("not found")

    return active_services


# =============================================================================
# File Count Tracking
# =============================================================================

def get_file_count(path):
    """Recursively count all files in a directory tree."""
    return sum(len(files) for _, _, files in os.walk(path))


def has_file_count_changed(library_path, web_path):
    """
    Check if the file count has changed since the last run.
    Returns True if HTML needs to be regenerated.
    """
    file_count_file = os.path.join(web_path, "file_count.txt")
    current_file_count = get_file_count(library_path)

    # Read previous file count if it exists
    previous_file_count = None
    if os.path.exists(file_count_file):
        try:
            with open(file_count_file, "r") as f:
                previous_file_count = int(f.read().strip())
        except (ValueError, IOError):
            previous_file_count = None

    if previous_file_count is not None and current_file_count == previous_file_count:
        print("File count has not changed.")
        return False

    print("File count has changed. Generating new HTML files.")

    # Save the current file count for future reference
    with open(file_count_file, "w") as f:
        f.write(str(current_file_count))

    # Remove existing HTML files
    os.system(f"rm -f {web_path}/*")

    return True


# =============================================================================
# HTML Generation
# =============================================================================

def get_html_template(nav_links, shutdown_url):
    """
    Build the HTML page template with navigation bar and table structure.

    Args:
        nav_links: string of HTML nav link elements
        shutdown_url: URL for the shutdown button

    Returns:
        HTML template string with TREE_CONTENT_PLACEHOLDER for content insertion
    """
    # Embed the bundled theme so every generated page works offline. Keeping it
    # in the template header also invalidates cached pages after a theme update.
    stylesheet = Path(__file__).with_name("style.css").read_text(encoding="utf-8")
    return f"""<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Library Index</title>
    <style>
{stylesheet}
    </style>
</head>
<body>
    <a class="skip-link" href="#library-content">Skip to files</a>
    <header>
        <div class="wrap topbar">
            <a class="brand" href="/">
                <img class="brand-logo" src="/library-brand.jpg" alt="" width="108" height="72">
                <span class="brand-tagline">Offline depository, in your hands</span>
            </a>
            <span class="badge">Library home</span>
        </div>
    </header>
    <main class="wrap">
        <div class="heading">
            <p class="eyebrow">YOUR OFFLINE LIBRARY</p>
            <h1>Bring knowledge with you.</h1>
            <p>Read, listen, explore, and discover the content on your Library drive.</p>
        </div>
        <section class="panel" aria-labelledby="services-title">
            <h2 id="services-title">Explore your Library</h2>
            <p>Choose a service or browse your files below.</p>
            <nav class="tabs" aria-label="Library services">
                <a href="/" aria-current="location">Home</a>
                {nav_links}
                <a class="shutdown" href="{escape(shutdown_url, quote=True)}">Shutdown</a>
            </nav>
        </section>
        <section class="panel" id="library-content" aria-labelledby="files-title" tabindex="-1">
            <div class="section-heading">
                <div><h2 id="files-title">Browse the library</h2><p>Open a folder to explore. Files open in a new tab.</p></div>
                <span class="badge">Saved on USB</span>
            </div>
            <!--FOLDER_NAV-->
            <div class="table-scroll">
                <table>
                    <thead><tr><th scope="col">File / folder</th><th scope="col">Type</th></tr></thead>
                    <tbody>
                        <!--TREE_CONTENT-->
                    </tbody>
                </table>
            </div>
        </section>
        <footer>Saved content stays on your USB drive and is available offline.<br>Use Shutdown before disconnecting power or removing the drive.</footer>
    </main>
</body>
</html>
"""


# Placeholder used in HTML templates for inserting page-specific content
TREE_CONTENT_PLACEHOLDER = "<!--TREE_CONTENT-->"
FOLDER_NAV_PLACEHOLDER = "<!--FOLDER_NAV-->"


def build_html_tree(path, web_path, html_template, base_url="/library/", current_page_url="/"):
    """
    Recursively build HTML table rows for the directory tree.
    Creates separate HTML pages for each subdirectory.

    Args:
        path: current directory path to process
        web_path: output directory for generated HTML files
        html_template: HTML template string with {tree_content} placeholder
        base_url: URL prefix for file links
        current_page_url: URL of this directory's index, used by its children's Back links

    Returns:
        HTML string of table rows for the current directory
    """
    output = ""

    for item in sorted(os.listdir(path)):
        # Skip hidden or system files
        if item.startswith("._") or item.startswith("."):
            continue

        full_path = os.path.join(path, item)

        if os.path.isdir(full_path):
            # Recurse into subdirectory
            subdir_content = build_html_tree(
                full_path, web_path, html_template,
                base_url + quote(item) + "/", f"/{quote(item)}.html"
            )
            # Create a separate HTML page for this subdirectory
            back_label = "Back to library" if current_page_url == "/" else "Back to parent folder"
            folder_nav = (
                '<nav class="folder-nav" aria-label="Folder navigation">'
                f'<a class="back-button" href="{escape(current_page_url, quote=True)}">'
                f'<span aria-hidden="true">←</span> {back_label}</a>'
                f'<span class="current-folder">{escape(item)}</span></nav>'
            )
            local_html = html_template.replace(FOLDER_NAV_PLACEHOLDER, folder_nav).replace(
                TREE_CONTENT_PLACEHOLDER, subdir_content)
            with open(os.path.join(web_path, f"{item}.html"), "w", encoding="utf-8") as f:
                f.write(local_html)
            output += (
                f'<tr><td><a class="file-link folder-link" href="{quote(item)}.html">'
                f'<span class="entry-icon" aria-hidden="true">▸</span><span>{escape(item)}</span></a></td>'
                '<td><span class="file-type folder-type">Folder</span></td></tr>'
            )
        else:
            # Create a link to the file
            link_name = item.replace("_", " ").rsplit(".", 1)[0]
            file_url = "/library" + base_url + quote(item)
            file_type = os.path.splitext(item)[1].lstrip(".").upper() or "File"
            output += (
                f'<tr><td><a class="file-link" href="{file_url}" target="_blank" rel="noopener noreferrer">'
                f'<span class="entry-icon" aria-hidden="true">↗</span><span>{escape(link_name)}</span></a></td>'
                f'<td><span class="file-type">{escape(file_type)}</span></td></tr>'
            )

    return output or '<tr><td colspan="2" class="empty">No files in this folder yet.</td></tr>'


# =============================================================================
# Nginx Configuration
# =============================================================================

def configure_nginx(webserver_config):
    """
    Generate and write the nginx configuration, then start or reload nginx.

    Args:
        webserver_config: dict with webserver settings from YAML
    """
    listen_port = webserver_config.get("nginx", {}).get("listen_port", 80)
    server_names = webserver_config.get("nginx", {}).get(
        "server_names", ["localhost", "library", "library.local", "10.1.1.1"]
    )
    server_names_str = " ".join(str(s) for s in server_names)
    web_path = webserver_config.get("web_path", "/library/web")

    nginx_config = f"""
server {{
    listen {listen_port};
    server_name {server_names_str};

    location / {{
        autoindex on;
        root {web_path};
        index index.html;
    }}

    location /library {{
        autoindex on;
        alias /library;
    }}

    location = /library-brand.jpg {{
        alias /usr/share/library-web/library.jpg;
    }}

    location /music {{
        proxy_pass http://10.88.0.210:5082;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-User music;
        proxy_read_timeout 120;
        proxy_buffering off;
        proxy_request_buffering off;
    }}

    # LMS static resources (Wt framework serves these at root paths)
    location /js/ {{
        proxy_pass http://10.88.0.210:5082/js/;
    }}

    location /css/ {{
        proxy_pass http://10.88.0.210:5082/css/;
    }}

    location /resources/ {{
        proxy_pass http://10.88.0.210:5082/resources/;
    }}

    location /images/ {{
        proxy_pass http://10.88.0.210:5082/images/;
    }}

    location /favicon.ico {{
        proxy_pass http://10.88.0.210:5082/favicon.ico;
    }}

    location /cgi-bin/ {{
        gzip off;
        root /root/cgi;
        fastcgi_pass unix:/var/run/fcgiwrap.socket;
        include /etc/nginx/fastcgi_params;
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
    }}
}}
"""

    # Write nginx config
    with open("/etc/nginx/sites-available/default", "w") as f:
        f.write(nginx_config)

    # Check if nginx is running
    nginx_running = os.system("pgrep nginx > /dev/null 2>&1")

    if nginx_running != 0:
        # Start nginx if not running
        print("Starting nginx...")
        os.system("nginx")
    else:
        # Reload nginx configuration
        print("Reloading nginx configuration...")
        os.system("nginx -s reload")


# =============================================================================
# Main Entry Point
# =============================================================================

def main():
    """Main execution flow for the library web interface generator."""

    # Load configuration from YAML
    config = load_config()

    # Extract webserver configuration
    webserver_config = config.get("webserver", DEFAULT_CONFIG["webserver"])
    library_path = webserver_config.get("library_path", "/library/library")
    web_path = webserver_config.get("web_path", "/library/web")
    host_ip = webserver_config.get("host_ip", "10.1.1.1")
    shutdown_port = webserver_config.get("shutdown_port", 9999)

    # Extract services configuration
    services_config = config.get("services", DEFAULT_CONFIG["services"])

    # --- Configure and start nginx ---
    configure_nginx(webserver_config)

    # --- Check which services are available ---
    print("\n--- Checking services ---")
    active_services = discover_services(services_config)
    nav_links = "\n        ".join(active_services)
    print(f"\nActive services: {len(active_services)}/{len(services_config)}")

    # --- Build the HTML template with nav bar ---
    shutdown_url = f"http://{host_ip}:{shutdown_port}"
    html_template = get_html_template(nav_links, shutdown_url)

    # Service availability can change without adding/removing library files.
    # Compare the generated header so new navigation also reaches cached pages.
    root_template = html_template.replace(FOLDER_NAV_PLACEHOLDER, "")
    expected_header = root_template.split(TREE_CONTENT_PLACEHOLDER, 1)[0]
    try:
        with open(os.path.join(web_path, "index.html"), "r") as f:
            navigation_changed = not f.read().startswith(expected_header)
    except OSError:
        navigation_changed = True
    if not has_file_count_changed(library_path, web_path) and not navigation_changed:
        return

    # --- Generate HTML pages ---
    print("\nGenerating HTML pages...")
    tree_content = build_html_tree(library_path, web_path, html_template)

    # Create the main index page
    index_html = root_template.replace(TREE_CONTENT_PLACEHOLDER, tree_content)
    with open(os.path.join(web_path, "index.html"), "w", encoding="utf-8") as f:
        f.write(index_html)

    print("HTML generation complete.")
    print(f"Index written to: {os.path.join(web_path, 'index.html')}")


if __name__ == "__main__":
    main()
