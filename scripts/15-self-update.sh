#!/usr/bin/env bash
# Install the self-update worker (scripts/self-update.py): lets the tablet
# pull new kiosk-software releases directly from GitHub, and separately
# check/apply Debian package upgrades — both triggered from the Setup
# page's Updates tab, no PC/SSH needed. curl + ca-certificates are
# guaranteed here rather than only via 08-install-camera.sh's apt line, so
# this keeps working under SKIP_CAMERA=1 too.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Run as root: sudo bash $0" >&2
  exit 1
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
INSTALL_ROOT=/opt/ha-kiosk

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y --no-install-recommends curl ca-certificates

install -d -m 755 "$INSTALL_ROOT/scripts" "$INSTALL_ROOT/logs"
install -m 755 "$ROOT/scripts/self-update.py" "$INSTALL_ROOT/scripts/self-update.py"

# Initial version marker only — never overwritten by a routine re-run of
# this script. A successful self-update writes the real applied version
# here itself (see self-update.py's `apply`), so this is only ever the
# fallback for a tablet that's never run a self-update yet.
if [[ ! -f "$INSTALL_ROOT/version" && -f "$ROOT/VERSION" ]]; then
  install -m 644 "$ROOT/VERSION" "$INSTALL_ROOT/version"
fi

echo "Self-update worker installed. Check for updates from the tablet's Setup > Updates tab."
