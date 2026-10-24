# Znacht on Proxmox (LXC)

One unprivileged Debian 12 LXC, Docker inside it, the compose file from `deploy/`. Fits next to the other service LXCs behind the Caddy LXC.

## Create the container

On the Proxmox host (adjust storage, bridge and IDs):

```bash
pveam update && pveam download local debian-12-standard_12.7-1_amd64.tar.zst
pct create 110 local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst \
  --hostname znacht --cores 2 --memory 1024 --swap 512 \
  --rootfs local-lvm:8 --net0 name=eth0,bridge=vmbr0,ip=dhcp \
  --unprivileged 1 --features nesting=1,keyctl=1 --start 1
pct exec 110 -- bash -c "apt-get update && apt-get install -y curl git ca-certificates && curl -fsSL https://get.docker.com | sh"
```

`nesting=1,keyctl=1` is what Docker needs inside an unprivileged LXC. Or run `deploy/lxc/create.sh` from the host, which does exactly this.

## Deploy

```bash
pct exec 110 -- bash -c "git clone https://github.com/sbarkar/znacht /opt/znacht"
pct exec 110 -- bash -c "cp /opt/znacht/deploy/.env.example /opt/znacht/deploy/.env"   # then edit it
pct exec 110 -- bash -c "cd /opt/znacht/deploy && docker compose up -d --build"
```

Put the household file in the volume: `docker cp household.yaml znacht:/data/household.yaml`. Reuse your Migros login: `docker cp ~/.config/migros-mcp/session.json znacht:/data/migros-session.json`.

Check: `curl http://<lxc-ip>:8787/healthz`, then `curl -X POST -H "Authorization: Bearer $TOKEN" http://<lxc-ip>:8787/api/plan_week` and open `/brief?token=$TOKEN`.

## Caddy

Add `deploy/caddy/Caddyfile.snippet` to the Caddy LXC with the znacht LXC's IP, reload Caddy, and set `ZNACHT_PUBLIC_URL` to that hostname so notification links work from phones.

## Update

```bash
pct exec 110 -- bash -c "cd /opt/znacht && git pull && cd deploy && docker compose up -d --build"
```

## Backups

Everything stateful is in the `znacht-data` volume: the SQLite database, the household YAML, the Cookidoo token and the Migros session. Proxmox Backup Server picks up the whole LXC; the volume alone is `docker run --rm -v znacht-data:/data -v $PWD:/out alpine tar czf /out/znacht-data.tgz /data`.
