#!/usr/bin/env bash
# Create the znacht LXC on a Proxmox host. Run on the host as root. Idempotent-ish: refuses if the ID exists.
set -euo pipefail
VMID="${VMID:-110}"
STORAGE="${STORAGE:-local-lvm}"
TEMPLATE_STORAGE="${TEMPLATE_STORAGE:-local}"
BRIDGE="${BRIDGE:-vmbr0}"
TEMPLATE="${TEMPLATE:-debian-12-standard_12.7-1_amd64.tar.zst}"

if pct status "$VMID" >/dev/null 2>&1; then
  echo "LXC $VMID already exists" >&2; exit 1
fi
pveam update >/dev/null
pveam list "$TEMPLATE_STORAGE" | grep -q "$TEMPLATE" || pveam download "$TEMPLATE_STORAGE" "$TEMPLATE"
pct create "$VMID" "$TEMPLATE_STORAGE:vztmpl/$TEMPLATE" \
  --hostname znacht --cores 2 --memory 1024 --swap 512 \
  --rootfs "$STORAGE:8" --net0 "name=eth0,bridge=$BRIDGE,ip=dhcp" \
  --unprivileged 1 --features nesting=1,keyctl=1 --onboot 1 --start 1
sleep 5
pct exec "$VMID" -- bash -c "apt-get update -qq && apt-get install -y -qq curl git ca-certificates >/dev/null && curl -fsSL https://get.docker.com | sh >/dev/null"
pct exec "$VMID" -- bash -c "git clone --depth 1 https://github.com/sbarkar/znacht /opt/znacht && cp /opt/znacht/deploy/.env.example /opt/znacht/deploy/.env"
echo "LXC $VMID is up. Next: edit /opt/znacht/deploy/.env inside it, copy household.yaml and the Migros session into /data, then:"
echo "  pct exec $VMID -- bash -c 'cd /opt/znacht/deploy && docker compose up -d --build'"
pct exec "$VMID" -- hostname -I
