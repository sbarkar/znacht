#!/usr/bin/env bash
# Create the znacht LXC on a Proxmox host and install the engine in it.
# Run on the Proxmox host as root (node shell in the web UI, or ssh). Refuses if the ID exists.
#
#   curl -fsSL https://raw.githubusercontent.com/sbarkar/znacht/main/deploy/lxc/create.sh | VMID=102 bash
#
# Knobs (env): VMID STORAGE TEMPLATE_STORAGE BRIDGE IP (dhcp or 192.168.4.12/24) GW TEMPLATE BRANCH
# RESUME=1 skips creation when the container already exists and only (re)runs the install inside it,
# for hosts where a pct guard (a pool restriction, say) interrupted the first run.
set -euo pipefail
export LC_ALL=C.UTF-8 LANG=C.UTF-8
VMID="${VMID:-102}"
STORAGE="${STORAGE:-local-lvm}"
TEMPLATE_STORAGE="${TEMPLATE_STORAGE:-local}"
BRIDGE="${BRIDGE:-vmbr0}"
IP="${IP:-dhcp}"
GW="${GW:-}"
TEMPLATE="${TEMPLATE:-}"
BRANCH="${BRANCH:-main}"

if pct status "$VMID" >/dev/null 2>&1; then
  if [ "${RESUME:-0}" = 1 ]; then
    echo "LXC $VMID exists; resuming with the install inside it"
    pct status "$VMID" | grep -q running || pct start "$VMID"
  else
    echo "LXC $VMID already exists (RESUME=1 re-runs the install inside it)" >&2
    exit 1
  fi
else
  # Newest Debian 12 template already on the storage, else download the current one.
  if [ -z "$TEMPLATE" ]; then
    TEMPLATE=$(pveam list "$TEMPLATE_STORAGE" | grep -o 'debian-12-standard_[^ ]*' | sort -V | tail -1 || true)
  fi
  if [ -z "$TEMPLATE" ]; then
    pveam update >/dev/null
    TEMPLATE=$(pveam available --section system | awk '{print $2}' | grep '^debian-12-standard' | sort -V | tail -1)
    pveam download "$TEMPLATE_STORAGE" "$TEMPLATE"
  fi

  NET="name=eth0,bridge=$BRIDGE,ip=$IP"
  [ -n "$GW" ] && NET="$NET,gw=$GW"

  pct create "$VMID" "$TEMPLATE_STORAGE:vztmpl/$TEMPLATE" \
    --hostname znacht --cores 2 --memory 1024 --swap 512 \
    --rootfs "$STORAGE:8" --net0 "$NET" \
    --unprivileged 1 --features nesting=1 --onboot 1 --start 1 \
    --tags znacht
fi

echo "waiting for the container's network"
for _ in $(seq 1 30); do
  pct exec "$VMID" -- getent hosts github.com >/dev/null 2>&1 && break
  sleep 2
done

pct exec "$VMID" -- env LC_ALL=C.UTF-8 DEBIAN_FRONTEND=noninteractive bash -c "apt-get update -qq && apt-get install -y -qq curl git ca-certificates >/dev/null"
pct exec "$VMID" -- env LC_ALL=C.UTF-8 BRANCH="$BRANCH" bash -c "curl -fsSL https://raw.githubusercontent.com/sbarkar/znacht/$BRANCH/deploy/lxc/install.sh | bash"

IPADDR=$(pct exec "$VMID" -- hostname -I | awk '{print $1}')
HOSTIP=$(hostname -I | awk '{print $1}')
if pct exec "$VMID" -- test -f /root/znacht-bundle.tgz; then
  echo "a bundle is already waiting inside; restoring it"
  pct exec "$VMID" -- /opt/znacht/deploy/lxc/restore.sh /root/znacht-bundle.tgz
  echo; echo "LXC $VMID (znacht) is up at $IPADDR with its secrets. Check: curl http://$IPADDR:8787/healthz"
  exit 0
fi
cat <<EOF

LXC $VMID (znacht) is up at $IPADDR. The engine is installed and waits for its secrets.

Next, on the machine that holds ~/.config/znacht, from the repo checkout:

  deploy/lxc/bundle.sh | ssh root@$HOSTIP "cat > /root/znacht-bundle.tgz && pct push $VMID /root/znacht-bundle.tgz /root/znacht-bundle.tgz && rm -f /root/znacht-bundle.tgz && pct exec $VMID -- /opt/znacht/deploy/lxc/restore.sh /root/znacht-bundle.tgz"

Then: curl http://$IPADDR:8787/healthz
EOF
