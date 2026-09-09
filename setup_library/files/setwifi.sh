set -euo pipefail

COUNTRY="${1:-US}"
CMDLINE="/boot/firmware/cmdline.txt"
SERVICE="/etc/systemd/system/wifi-rfkill-unblock.service"

echo "========================================"
echo " Raspberry Pi Wi-Fi Configuration"
echo " Country: ${COUNTRY}"
echo "========================================"

# ------------------------------------------------------------
# 1. Set Wi-Fi country using raspi-config when available
# ------------------------------------------------------------

if command -v raspi-config >/dev/null 2>&1; then
    echo "Setting Wi-Fi country to ${COUNTRY} using raspi-config..."

    if raspi-config nonint do_wifi_country "${COUNTRY}" 2>/dev/null; then
        echo "Wi-Fi country configured."
    else
        echo "raspi-config country configuration failed; continuing with kernel regdom."
    fi
fi

# ------------------------------------------------------------
# 2. Set kernel regulatory domain
# ------------------------------------------------------------

if [[ -f "${CMDLINE}" ]]; then
    echo "Configuring ${CMDLINE}..."

    # Remove any existing regulatory-domain setting
    sed -i -E \
        's/(^|[[:space:]])cfg80211\.ieee80211_regdom=[A-Za-z]{2}([[:space:]]|$)/ /g' \
        "${CMDLINE}"

    # Collapse accidental duplicate spaces
    sed -i -E 's/[[:space:]]+/ /g; s/^ //; s/ $//' "${CMDLINE}"

    # Append regulatory domain
    sed -i "1 s/$/ cfg80211.ieee80211_regdom=${COUNTRY}/" "${CMDLINE}"

    echo "Kernel regulatory domain set to ${COUNTRY}."
else
    echo "WARNING: ${CMDLINE} not found."
fi

# ------------------------------------------------------------
# 3. Unblock Wi-Fi immediately
# ------------------------------------------------------------

echo "Unblocking Wi-Fi..."

if command -v rfkill >/dev/null 2>&1; then
    rfkill unblock wifi || true
    rfkill unblock wlan || true
else
    echo "WARNING: rfkill command not installed."
fi

# ------------------------------------------------------------
# 4. Install systemd service to unblock Wi-Fi every boot
# ------------------------------------------------------------

echo "Installing Wi-Fi rfkill systemd service..."

cat > "${SERVICE}" <<'EOF'
[Unit]
Description=Ensure Wi-Fi is unblocked
After=systemd-rfkill.service
Before=NetworkManager.service
Before=networking.service
Before=dhcpcd.service

[Service]
Type=oneshot
ExecStart=/usr/sbin/rfkill unblock wifi
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable wifi-rfkill-unblock.service

# Run it now as well
systemctl restart wifi-rfkill-unblock.service || true

# ------------------------------------------------------------
# 5. Display current status
# ------------------------------------------------------------

echo
echo "Current RFKill status:"
rfkill list 2>/dev/null || true

echo
echo "Current regulatory domain:"
iw reg get 2>/dev/null | head -20 || true
