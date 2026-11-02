#!/usr/bin/env bash
set -euo pipefail
case "$(dpkg --print-architecture)" in
    amd64) arch=x86_64 ;;
    arm64) arch=aarch64 ;;
    *) echo 'Library Office supports amd64 and arm64.' >&2; exit 1 ;;
esac
apt-get update
apt-get install -y --no-install-recommends ca-certificates curl fonts-dejavu-core fonts-liberation
mkdir -p /tmp/craft-packages /usr/local/share/library-office
cd /tmp/craft-packages
for app_version in wordcraft:0.13.2 deckcraft:0.13.1 gridcraft:0.14.2; do
    app=${app_version%:*}
    version=${app_version#*:}
    package="${app}-${version}-linux-${arch}.deb"
    curl --fail --location --retry 3 --output "$package" \
        "https://github.com/storytold/${app}/releases/download/v${version}/${package}"
    grep -F "  ${package}" /opt/library-office/packages.sha256 | sha256sum --check --strict -
done
apt-get install -y --no-install-recommends /tmp/craft-packages/*.deb
for app in wordcraft deckcraft gridcraft; do
    command -v "$app"
    cat > "/usr/local/share/library-office/${app}.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=${app^}
Exec=${app} %F
Path=/documents
Icon=applications-office
Terminal=false
Categories=Office;
EOF
done
cp /opt/library-office/packages.sha256 /usr/local/share/library-office/packages.sha256
rm -rf /tmp/craft-packages /var/lib/apt/lists/*
