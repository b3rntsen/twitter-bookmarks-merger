#!/bin/bash
# Install a pinned, checksum-verified docker buildx on the production EC2 host.
# Idempotent — safe to re-run. Run on the instance: sudo bash install-buildx.sh
#
# AL2023's docker package ships buildx 0.12, but the hand-installed Compose v5 plugin
# needs >= 0.17, so `docker compose build` fails without this. The binary goes to
# /usr/local/lib/docker/cli-plugins, which the docker CLI searches before the
# package's /usr/libexec copy, so dnf updates don't undo it.
#
# Source: https://github.com/docker/buildx/releases (sha256 from that release's checksums.txt).
# To upgrade, change both lines below.

set -euo pipefail

VERSION=v0.38.1
SHA256=e25d5cd675092bb5d1d03632fdc46cdf3fede7b514dc5f023a105e00d3ce5ad4

DEST=/usr/local/lib/docker/cli-plugins/docker-buildx
if [ -x "$DEST" ] && echo "$SHA256  $DEST" | sha256sum -c --status; then
    echo "buildx $VERSION already installed"
else
    tmp=$(mktemp)
    trap 'rm -f "$tmp"' EXIT
    curl -fsSL -o "$tmp" "https://github.com/docker/buildx/releases/download/$VERSION/buildx-$VERSION.linux-amd64"
    echo "$SHA256  $tmp" | sha256sum -c --quiet
    install -D -m 0755 "$tmp" "$DEST"
fi

docker buildx version
