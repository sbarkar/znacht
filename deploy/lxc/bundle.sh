#!/usr/bin/env bash
# Pack the engine's secrets and state for the LXC and write a tar.gz to STDOUT. Nothing lands on disk here.
# Run on the machine that has ~/.config/znacht, and pipe into ssh (deploy/lxc/create.sh prints the line).
#
#   deploy/lxc/bundle.sh | ssh root@<proxmox-host> "cat > /root/znacht-bundle.tgz && pct push <vmid> ... "
#
# In the LXC itself (to move to the Home Assistant add-on, which imports the bundle on start), the env is in
# /etc/znacht and the rest in /var/lib/znacht; stop the engine first so tokens and database stand still:
#
#   ZNACHT_CONFIG_DIR=/etc/znacht ZNACHT_DATA_DIR=/var/lib/znacht bundle.sh > znacht-bundle.tgz
#
# Contents: env (minus the workstation paths; the service sets its own), household.yaml, the Cookidoo token,
# the Migros session, and a consistent copy of the SQLite database so run history carries over.
# PUBLIC_URL=https://znacht.example.ch sets ZNACHT_PUBLIC_URL; without it restore.sh uses the LXC's address.
set -euo pipefail
CFG="${ZNACHT_CONFIG_DIR:-$HOME/.config/znacht}"
DATA="${ZNACHT_DATA_DIR:-$HOME/.local/share/znacht}"
PUBLIC_URL="${PUBLIC_URL:-}"

if [ -t 1 ]; then
  echo "bundle.sh writes a tarball to stdout; pipe it into ssh (see deploy/lxc/README.md)" >&2
  exit 2
fi
# Each file from the config dir, else the data dir (the LXC keeps only the env apart).
find_file() { for d in "$CFG" "$DATA"; do [ -f "$d/$1" ] && { echo "$d/$1"; return; }; done; return 1; }
[ -f "$CFG/env" ] || { echo "no $CFG/env" >&2; exit 1; }
HOUSEHOLD="$(find_file household.yaml)" || { echo "no household.yaml in $CFG or $DATA" >&2; exit 1; }

T=$(mktemp -d)
chmod 700 "$T"
trap 'rm -rf "$T"' EXIT

grep -vE '^(ZNACHT_DATA_DIR|ZNACHT_HOUSEHOLD|ZNACHT_COOKIDOO_TOKEN_FILE|ZNACHT_MIGROS_SESSION_FILE|ZNACHT_PUBLIC_URL)=' "$CFG/env" > "$T/env"
[ -n "$PUBLIC_URL" ] && echo "ZNACHT_PUBLIC_URL=\"$PUBLIC_URL\"" >> "$T/env"
# Adapter choice: whatever the env file says, else the current shell, else the live defaults.
for pair in ZNACHT_RECIPE_SOURCE=cookidoo ZNACHT_SINK=cookidoo ZNACHT_STORE=migros ZNACHT_PLANNER=anthropic; do
  k="${pair%%=*}"
  grep -q "^$k=" "$T/env" || echo "$k=\"${!k:-${pair#*=}}\"" >> "$T/env"
done
cp "$HOUSEHOLD" "$T/"
for f in cookidoo-token.json migros-session.json; do
  src="$(find_file "$f")" && cp "$src" "$T/"
done
if [ -f "$DATA/znacht.sqlite" ]; then
  python3 - "$DATA/znacht.sqlite" "$T/znacht.sqlite" <<'PY' || cp "$DATA/znacht.sqlite" "$T/"
import sqlite3, sys
src, dst = sqlite3.connect(sys.argv[1]), sqlite3.connect(sys.argv[2])
src.backup(dst)
dst.close(); src.close()
PY
fi

tar czf - -C "$T" .
echo "bundled: $(ls "$T" | tr '\n' ' ')" >&2
