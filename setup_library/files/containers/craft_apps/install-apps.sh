#!/usr/bin/env bash
set -euo pipefail
case "$(dpkg --print-architecture)" in
    amd64) arch=x86_64 ;;
    arm64) arch=aarch64 ;;
    *) echo 'Library Office supports amd64 and arm64.' >&2; exit 1 ;;
esac
apt-get update
apt-get install -y --no-install-recommends ca-certificates curl jq fonts-dejavu-core fonts-liberation
mkdir -p /tmp/craft-packages /usr/local/share/library-office
cd /tmp/craft-packages
# Resolve one stable release per app, then download that release's exact asset.
: > /usr/local/share/library-office/packages.sha256
: > /usr/local/share/library-office/releases.txt
for app in wordcraft deckcraft gridcraft; do
    curl --fail --location --retry 3 \
        --header 'Accept: application/vnd.github+json' \
        --output "${app}-release.json" \
        "https://api.github.com/repos/storytold/${app}/releases/latest"
    release=$(jq -er '.tag_name | select(type == "string" and length > 0)' "${app}-release.json")
    asset=$(jq -cer --arg app "$app" --arg arch "$arch" '
        [.assets[] | select(.name | startswith($app + "-")) |
         select(.name | endswith("-linux-" + $arch + ".deb"))] |
        if length == 1 then .[0] else error("Expected one Linux deb asset") end
    ' "${app}-release.json")
    package=$(jq -er '.name' <<< "$asset")
    url=$(jq -er '.browser_download_url' <<< "$asset")
    digest=$(jq -er '.digest | select(type == "string") |
        select(test("^sha256:[0-9a-f]{64}$"))' <<< "$asset")
    [[ "$package" != */* && "$url" == "https://github.com/storytold/${app}/releases/download/"* ]] || {
        echo "Unexpected release asset for $app" >&2; exit 1;
    }
    echo "Installing ${app} ${release} (${arch})"
    curl --fail --location --retry 3 --output "$package" "$url"
    printf '%s  %s\n' "${digest#sha256:}" "$package" | sha256sum --check --strict -
    printf '%s  %s\n' "${digest#sha256:}" "$package" >> /usr/local/share/library-office/packages.sha256
    printf '%s %s\n' "$app" "$release" >> /usr/local/share/library-office/releases.txt
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
rm -rf /tmp/craft-packages /var/lib/apt/lists/*
