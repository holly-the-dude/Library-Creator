#!/usr/bin/python3
"""
Library Hotspot Service

Sets up a WiFi access point (hotspot) on wlan0 so users can connect directly
to the Library system without an existing network. This script:

1. Brings up the wlan0 interface
2. Assigns a static IP (10.1.1.1/24)
3. Starts hostapd to broadcast SSID 'library' on channel 7
4. Starts dnsmasq to provide DHCP and DNS (resolves library/library.local
   to 10.1.1.1 so clients can reach the webserver by name)

Each step includes verification and retry logic — WiFi hardware can be slow
to initialize, so the script retries each step several times before giving up.

Requirements:
    - hostapd (WiFi access point daemon)
    - dnsmasq (DNS/DHCP server)
    - iproute2 (ip command)
    - Access to wlan0 device (--device=/dev/net/tun or --privileged)
"""

import os
import subprocess
import time

# =============================================================================
# Configuration
# =============================================================================

# Number of times to retry each step before giving up
MAX_RETRIES = 5

# Seconds to wait between retries (gives hardware/services time to settle)
RETRY_DELAY = 2

# Network settings
INTERFACE = "wlan0"
STATIC_IP = "10.1.1.1/24"
DHCP_RANGE_START = "10.1.1.10"
DHCP_RANGE_END = "10.1.1.100"
DHCP_LEASE_TIME = "24h"


# =============================================================================
# Utility Functions
# =============================================================================

def retry(func, description, max_retries=MAX_RETRIES, delay=RETRY_DELAY):
    """
    Run a function up to max_retries times until it succeeds.

    Args:
        func: Callable that returns True on success, False on failure.
        description: Human-readable name of the step (for logging).
        max_retries: Maximum number of attempts.
        delay: Seconds to wait between retries.

    Returns:
        bool: True if the function succeeded within the retry limit.
    """
    for attempt in range(1, max_retries + 1):
        print(f"[{description}] Attempt {attempt}/{max_retries}...")
        if func():
            print(f"[{description}] Success.")
            return True
        if attempt < max_retries:
            print(f"[{description}] Failed, retrying in {delay}s...")
            time.sleep(delay)
    print(f"[{description}] FAILED after {max_retries} attempts.")
    return False


def is_process_running(name):
    """
    Check if a process with the given name is running.

    Args:
        name: Process name to search for (matched against full command line).

    Returns:
        bool: True if at least one matching process is found.
    """
    try:
        output = subprocess.check_output(['pgrep', '-f', name], stderr=subprocess.DEVNULL)
        return len(output.strip()) > 0
    except subprocess.CalledProcessError:
        return False


def kill_process(name):
    """
    Kill any running process matching the given name.
    Used to clean up before retrying a service start.
    """
    try:
        subprocess.call(['pkill', '-f', name], stderr=subprocess.DEVNULL)
        time.sleep(0.5)  # Give it a moment to die
    except Exception:
        pass


# =============================================================================
# Network Interface Setup
# =============================================================================

def start_wlan0():
    """
    Bring up the wlan0 wireless interface and verify it's up.

    The container must have access to the host's wlan0 device, typically
    passed in with --network=host or --device flags.

    Returns:
        bool: True if interface is up, False otherwise.
    """
    try:
        subprocess.check_call(['ip', 'link', 'set', INTERFACE, 'up'],
                              stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        return False

    # Verify the interface is actually up
    try:
        output = subprocess.check_output(['ip', 'link', 'show', INTERFACE],
                                         stderr=subprocess.DEVNULL).decode()
        return 'UP' in output
    except subprocess.CalledProcessError:
        return False


def set_static_ip():
    """
    Assign static IP 10.1.1.1/24 to wlan0 and verify it's applied.

    This IP becomes the gateway and DNS server for hotspot clients.
    Using 'replace' instead of 'add' avoids errors if the address
    already exists from a previous run.

    Returns:
        bool: True if IP is set correctly, False otherwise.
    """
    try:
        subprocess.check_call(['ip', 'addr', 'replace', STATIC_IP, 'dev', INTERFACE],
                              stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        return False

    # Verify the IP was actually assigned
    try:
        output = subprocess.check_output(['ip', 'addr', 'show', INTERFACE],
                                         stderr=subprocess.DEVNULL).decode()
        return STATIC_IP in output
    except subprocess.CalledProcessError:
        return False


# =============================================================================
# hostapd - WiFi Access Point
# =============================================================================

def start_hostapd():
    """
    Start hostapd to create a WiFi access point and verify it's running.

    Configuration:
        - SSID: library (open network, no password)
        - Channel: 7 (2.4 GHz band)
        - Driver: nl80211 (standard Linux wireless driver)
        - No MAC filtering (macaddr_acl=0)
        - Broadcast SSID visible (ignore_broadcast_ssid=0)

    If hostapd is already running (from a previous attempt), it's killed
    first to ensure a clean start.

    Returns:
        bool: True if hostapd is running after start, False otherwise.
    """
    # Kill any existing hostapd before retrying
    kill_process('hostapd')

    # hostapd configuration - open network for easy library access
    config = """interface={interface}
driver=nl80211
ssid=library
hw_mode=g
channel=7
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
""".format(interface=INTERFACE)

    with open('/tmp/hostapd.conf', 'w') as f:
        f.write(config)

    try:
        subprocess.Popen(['hostapd', '/tmp/hostapd.conf'],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        print(f"  Error launching hostapd: {e}")
        return False

    # Give hostapd time to initialize and bind to the interface
    time.sleep(2)

    # Verify hostapd is actually running
    return is_process_running('hostapd')


# =============================================================================
# dnsmasq - DHCP and DNS
# =============================================================================

def start_dnsmasq():
    """
    Start dnsmasq to provide DHCP and DNS services and verify it's running.

    DHCP Configuration:
        - Range: 10.1.1.10 - 10.1.1.100 (91 clients max)
        - Subnet: 255.255.255.0 (/24)
        - Lease time: 24 hours
        - DNS server pushed to clients: 10.1.1.1 (this host)

    DNS Configuration:
        - 'library' resolves to 10.1.1.1
        - 'library.local' resolves to 10.1.1.1
        - no-resolv: don't read /etc/resolv.conf (no upstream DNS)
        - bind-interfaces: only listen on wlan0

    This means clients can type 'http://library' in their browser to reach
    the webserver container. No internet access is provided — this is an
    isolated local library network.

    If dnsmasq is already running (from a previous attempt), it's killed
    first to ensure a clean start.

    Returns:
        bool: True if dnsmasq is running after start, False otherwise.
    """
    # Kill any existing dnsmasq before retrying
    kill_process('dnsmasq')

    # dnsmasq configuration for local DNS + DHCP
    dnsmasq_config = """address=/library/10.1.1.1
address=/library.local/10.1.1.1
interface={interface}
dhcp-range={start},{end},255.255.255.0,{lease}
dhcp-option=6,10.1.1.1
no-resolv
bind-interfaces
""".format(interface=INTERFACE, start=DHCP_RANGE_START,
           end=DHCP_RANGE_END, lease=DHCP_LEASE_TIME)

    with open('/tmp/dnsmasq.conf', 'w') as f:
        f.write(dnsmasq_config)

    try:
        # Run dnsmasq in foreground (-d) so it stays alive as the main process
        subprocess.Popen(['dnsmasq', '-C', '/tmp/dnsmasq.conf', '-d'],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        print(f"  Error launching dnsmasq: {e}")
        return False

    # Give dnsmasq time to bind
    time.sleep(1)

    # Verify dnsmasq is actually running
    return is_process_running('dnsmasq')


# =============================================================================
# Main Entry Point
# =============================================================================

def main():
    """
    Start the hotspot by running each setup step in sequence with retries.

    Each step is retried up to MAX_RETRIES times. Steps are run in dependency
    order — if any step fails after all retries, the script exits since later
    steps depend on earlier ones succeeding.
    """
    print("Starting Library hotspot...")
    print(f"  Interface: {INTERFACE}")
    print(f"  IP: {STATIC_IP}")
    print(f"  SSID: library")
    print(f"  DHCP range: {DHCP_RANGE_START} - {DHCP_RANGE_END}")
    print(f"  Max retries per step: {MAX_RETRIES}")
    print()

    if not retry(start_wlan0, "wlan0 up"):
        print("FATAL: Could not bring up wlan0. Exiting.")
        return

    if not retry(set_static_ip, "static IP"):
        print("FATAL: Could not set static IP. Exiting.")
        return

    if not retry(start_hostapd, "hostapd"):
        print("FATAL: Could not start hostapd. Exiting.")
        return

    if not retry(start_dnsmasq, "dnsmasq"):
        print("FATAL: Could not start dnsmasq. Exiting.")
        return

    print()
    print("Hotspot is running successfully.")
    print(f"  SSID: library (open)")
    print(f"  Gateway: 10.1.1.1")
    print(f"  DNS: library -> 10.1.1.1, library.local -> 10.1.1.1")


if __name__ == "__main__":
    main()
