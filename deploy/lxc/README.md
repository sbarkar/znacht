# Znacht on Proxmox (LXC)

One unprivileged Debian 12 LXC, the engine as a systemd service under a dedicated user, no Docker. Home
Assistant and the phones talk to it over the LAN; the Caddy LXC can put HTTPS in front for links that
leave the house. This is the tested path; `deploy/compose.yaml` is the same engine for people who prefer a
container.

Four scripts, each does one thing:

| script | runs on | does |
|---|---|---|
| `create.sh` | Proxmox host | creates the LXC and runs `install.sh` inside it |
| `install.sh` | inside the LXC | git checkout in `/opt/znacht`, uv-managed Python 3.12 venv, `znacht.service`; re-run to update |
| `bundle.sh` | the machine with `~/.config/znacht` | tars the env, household, Cookidoo token, Migros session and database to stdout |
| `restore.sh` | inside the LXC | unpacks the bundle into `/etc/znacht/env` and `/var/lib/znacht`, starts the service |

## 1. Create

On the Proxmox host as root:

```bash
curl -fsSL https://raw.githubusercontent.com/sbarkar/znacht/main/deploy/lxc/create.sh | VMID=102 bash
```

Knobs via env: `VMID`, `STORAGE` (local-lvm), `BRIDGE` (vmbr0), `IP` (`dhcp` or `192.168.4.12/24` plus `GW`),
`TEMPLATE` (newest Debian 12 on `local` by default), `BRANCH`. It prints the container's address and the
bundle line for step 2.

If a `pct` guard on your host stops the run after the container exists (a pool restriction, for instance),
fix the guard, then re-run with `RESUME=1`: it skips creation, installs inside, and restores a bundle that
already arrived.

## 2. Move the secrets over

From the repo checkout on the machine that has `~/.config/znacht` (the host address and VMID come from
step 1's output):

```bash
deploy/lxc/bundle.sh | ssh root@192.168.4.10 "cat > /root/znacht-bundle.tgz && pct push 102 /root/znacht-bundle.tgz /root/znacht-bundle.tgz && rm -f /root/znacht-bundle.tgz && pct exec 102 -- /opt/znacht/deploy/lxc/restore.sh /root/znacht-bundle.tgz"
```

The tarball only ever exists in the pipe, briefly in `/root` on the host, and in the LXC until `restore.sh`
shreds it. `PUBLIC_URL=https://znacht.example.ch deploy/lxc/bundle.sh | ...` sets the public URL used in
notification links; otherwise it is the LXC's own address.

## 3. Check and connect

```bash
curl http://<lxc-ip>:8787/healthz
```

In Home Assistant: Settings → Devices & services → Znacht → Reconfigure, enter `http://<lxc-ip>:8787`
and the token from your env file. Entities and history stay; the sidebar panel follows the new URL after
the integration reloads. Then stop the old engine and close its firewall port.

## Update

```bash
pct exec 102 -- /opt/znacht/deploy/lxc/install.sh
```

## Logs

```bash
pct exec 102 -- journalctl -u znacht -n 100 -f
```

## Caddy (optional)

Add `deploy/caddy/Caddyfile.snippet` to the Caddy LXC with the znacht LXC's IP, reload Caddy, and re-run
step 2 with `PUBLIC_URL=https://<your host>` (or edit `ZNACHT_PUBLIC_URL` in `/etc/znacht/env` and
`systemctl restart znacht`). With HTTPS in front, point Home Assistant at the HTTPS URL too; an HTTPS Home
Assistant (Nabu Casa) needs this for the sidebar iframe.

## Backups

Everything stateful is in `/var/lib/znacht`: the SQLite database, the household YAML, the Cookidoo token and
the Migros session. Proxmox Backup Server picks up the whole LXC.
