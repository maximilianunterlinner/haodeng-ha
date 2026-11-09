#!/usr/bin/env bash
# Pull the latest version of this repo and deploy the integration into a
# Home Assistant *container* installation, then restart Home Assistant.
#
# Usage (from anywhere):   ~/haodeng-ha/scripts/update-ha.sh
# Without restart:         ~/haodeng-ha/scripts/update-ha.sh --no-restart
#
# Paths can be overridden via environment variables:
#   HA_CONFIG   Home Assistant config dir on the host   (default: ~/ha-stack/homeassistant/config)
#   HA_STACK    directory containing docker-compose.yml (default: ~/ha-stack)
#   HA_SERVICE  compose service name                    (default: homeassistant)
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HA_CONFIG="${HA_CONFIG:-$HOME/ha-stack/homeassistant/config}"
HA_STACK="${HA_STACK:-$HOME/ha-stack}"
HA_SERVICE="${HA_SERVICE:-homeassistant}"
SRC="$REPO_DIR/custom_components/haodeng_mesh"
DEST="$HA_CONFIG/custom_components/haodeng_mesh"

version() { grep -o '"version": *"[^"]*"' "$1/manifest.json" 2>/dev/null | cut -d'"' -f4 || true; }

if [[ ! -f "$HA_CONFIG/configuration.yaml" ]]; then
  echo "FEHLER: $HA_CONFIG sieht nicht wie ein Home-Assistant-Config-Ordner aus." >&2
  exit 1
fi

echo "==> Hole neueste Version"
git -C "$REPO_DIR" pull --ff-only

old="$(version "$DEST")"
new="$(version "$SRC")"
echo "==> Installiert: ${old:-keine}  ->  neu: $new"

echo "==> Kopiere nach $DEST"
sudo mkdir -p "$HA_CONFIG/custom_components"
sudo rsync -a --delete --exclude '__pycache__' "$SRC/" "$DEST/"

if [[ "${1:-}" == "--no-restart" ]]; then
  echo "==> Fertig (ohne Neustart)."
  exit 0
fi

echo "==> Starte Home Assistant neu"
(cd "$HA_STACK" && docker compose restart "$HA_SERVICE")
echo "==> Fertig. Log ansehen mit:"
echo "    cd $HA_STACK && docker compose logs --since 3m $HA_SERVICE | grep -i haodeng"
