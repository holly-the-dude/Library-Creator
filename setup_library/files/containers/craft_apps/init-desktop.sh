#!/usr/bin/env bash
set -euo pipefail
# The host creates and owns the shared folder; do not recursively chown its files.
if ! mountpoint -q /documents; then
    echo 'Mount the host documents directory at /documents before starting Library Office.' >&2
    exit 1
fi
mkdir -p /config/Desktop /config/.config/autostart /config/.config/gtk-3.0
if [[ ! -e /config/Documents && ! -L /config/Documents ]]; then
    ln -s /documents /config/Documents
fi
for app in wordcraft deckcraft gridcraft; do
    target="/config/Desktop/${app}.desktop"
    if [[ ! -e "$target" ]]; then
        install -m 0755 -o abc -g abc "/usr/local/share/library-office/${app}.desktop" "$target"
    fi
done
cat > /config/Desktop/Documents.desktop <<'EOF'
[Desktop Entry]
Type=Application
Name=Documents
Comment=Files saved on the Library drive
Exec=thunar /documents
Path=/documents
Icon=folder-documents
Terminal=false
EOF
chmod +x /config/Desktop/Documents.desktop
cat > /config/.config/autostart/library-office.desktop <<'EOF'
[Desktop Entry]
Type=Application
Name=Library Office desktop defaults
Exec=/usr/local/bin/office-desktop-defaults
OnlyShowIn=XFCE;
EOF
touch /config/.config/gtk-3.0/bookmarks
if ! grep -q '^file:///documents\( \|$\)' /config/.config/gtk-3.0/bookmarks; then
    printf '%s\n' 'file:///documents Documents' >> /config/.config/gtk-3.0/bookmarks
fi
chown abc:abc /config/Desktop/Documents.desktop /config/.config/autostart \
    /config/.config/autostart/library-office.desktop /config/.config/gtk-3.0 \
    /config/.config/gtk-3.0/bookmarks
# Set the desktop's Documents shortcut to the host-backed folder.
touch /config/.config/user-dirs.dirs
sed -i '/^XDG_DOCUMENTS_DIR=/d' /config/.config/user-dirs.dirs
printf '%s\n' 'XDG_DOCUMENTS_DIR="/documents"' >> /config/.config/user-dirs.dirs
chown abc:abc /config/Desktop /config/.config /config/.config/user-dirs.dirs
if ! s6-setuidgid abc test -w /documents; then
    echo 'Library Office cannot write /documents: match PUID/PGID to the host folder owner.' >&2
    exit 1
fi
