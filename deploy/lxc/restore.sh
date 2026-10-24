#!/usr/bin/env bash
# Unpack a bundle from deploy/lxc/bundle.sh into place and (re)start the engine. Run as root inside the LXC.
# The bundle file is shredded afterwards, whatever happens.
set -euo pipefail
B="${1:?usage: restore.sh <bundle.tgz>}"
DATA=/var/lib/znacht
ENVFILE=/etc/znacht/env

T=$(mktemp -d)
chmod 700 "$T"
trap 'rm -rf "$T"; shred -u "$B" 2>/dev/null || rm -f "$B"' EXIT

tar xzf "$B" -C "$T"
[ -f "$T/env" ] || { echo "bundle has no env file" >&2; exit 1; }

if ! grep -q '^ZNACHT_PUBLIC_URL=' "$T/env"; then
  echo "ZNACHT_PUBLIC_URL=\"http://$(hostname -I | awk '{print $1}'):8787\"" >> "$T/env"
fi

install -d -m 750 -o root -g znacht /etc/znacht
install -m 640 -o root -g znacht "$T/env" "$ENVFILE"
install -d -m 750 -o znacht -g znacht "$DATA"
for f in household.yaml cookidoo-token.json migros-session.json znacht.sqlite; do
  [ -f "$T/$f" ] && install -m 600 -o znacht -g znacht "$T/$f" "$DATA/$f"
done

systemctl restart znacht
sleep 3
systemctl --no-pager --lines=3 status znacht || true
curl -fsS http://127.0.0.1:8787/healthz && echo
