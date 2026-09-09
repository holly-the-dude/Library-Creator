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
                 internal_port, external_url, check_text, timeout

    Returns:
        HTML string for the nav link if service is up, empty string otherwise.
    """
    internal_ip = service.get("internal_ip", "")
    internal_port = service.get("internal_port", "")
    check_text = service.get("check_text", "")
    timeout = service.get("timeout", 5)
    display_name = service.get("display_name", service.get("name", "Unknown"))
    external_url = service.get("external_url", "")

    url = f"http://{internal_ip}:{internal_port}"

    try:
        response = requests.get(url, timeout=timeout)
        if check_text in response.content.decode("utf-8"):
            return (
                f'<a style="font-size: 24px"; href="{external_url}" '
                f'target="_blank">{display_name}</a> |'
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
        print("File count has not changed. Skipping HTML generation.")
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
    return f"""<html>
<head>
    <title>Library Index</title>
    <style>
        table {{
            width: 100%;
            border-collapse: collapse;
        }}
        td, th {{
            border: 1px solid #ddd;
            padding: 8px;
            font-size: 24px;
            font-weight: bold;
        }}
        tr:nth-child(even) {{
            background-color: #f2f2f2;
        }}
        tr:hover {{
            background-color: #ddd;
        }}
    </style>
</head>
<body>
    <div>
        <a style="font-size: 24px"; href="/">Home</a> |
        {nav_links}
        <a style="font-size: 24px"; href="{shutdown_url}">Shutdown</a>
    </div>
    <table>
        <thead>
            <tr>
                <th>Categories</th>
            </tr>
        </thead>
        <tbody>
            <!--TREE_CONTENT-->
        </tbody>
    </table>
</body>
</html>
"""


# Placeholder used in HTML templates for inserting page-specific content
TREE_CONTENT_PLACEHOLDER = "<!--TREE_CONTENT-->"


def build_html_tree(path, web_path, html_template, base_url="/library/"):
    """
    Recursively build HTML table rows for the directory tree.
    Creates separate HTML pages for each subdirectory.

    Args:
        path: current directory path to process
        web_path: output directory for generated HTML files
        html_template: HTML template string with {tree_content} placeholder
        base_url: URL prefix for file links

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
                base_url + quote(item) + "/"
            )
            # Create a separate HTML page for this subdirectory
            local_html = html_template.replace(TREE_CONTENT_PLACEHOLDER, subdir_content)
            with open(os.path.join(web_path, f"{item}.html"), "w") as f:
                f.write(local_html)
            output += f'<tr><td><a href="{quote(item)}.html">{item}</a></td></tr>'
        else:
            # Create a link to the file
            link_name = item.replace("_", " ").rsplit(".", 1)[0]
            file_url = "/library" + base_url + quote(item)
            output += (
                f'<tr><td><a href="{file_url}" target="_blank">'
                f"{link_name}</a></td></tr>"
            )

    return output


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

    # --- Check if HTML regeneration is needed ---
    if not has_file_count_changed(library_path, web_path):
        return

    # --- Build the HTML template with nav bar ---
    shutdown_url = f"http://{host_ip}:{shutdown_port}"
    html_template = get_html_template(nav_links, shutdown_url)

    # --- Generate HTML pages ---
    print("\nGenerating HTML pages...")
    tree_content = build_html_tree(library_path, web_path, html_template)

    # Create the main index page
    index_html = html_template.replace(TREE_CONTENT_PLACEHOLDER, tree_content)
    with open(os.path.join(web_path, "index.html"), "w") as f:
        f.write(index_html)

    print("HTML generation complete.")
    print(f"Index written to: {os.path.join(web_path, 'index.html')}")


if __name__ == "__main__":
    main()
