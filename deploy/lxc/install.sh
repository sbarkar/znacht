#!/usr/bin/env bash
# Install or update the Znacht engine on a Debian/Ubuntu box as a systemd service. Run as root. Idempotent.
#
# Layout: code in /opt/znacht (git checkout, uv-managed venv), state in /var/lib/znacht (owned by the
# service user), secrets in /etc/znacht/env (root:znacht 640). The service runs the engine exactly the way
# the dev setup does: `uv run --env-file ... znacht-engine`, so the env file is parsed the same everywhere.
#
# Re-run to update: pulls the branch, re-syncs the venv, restarts the service.
set -euo pipefail
BRANCH="${BRANCH:-main}"
REPO="${REPO:-https://github.com/sbarkar/znacht}"
APP=/opt/znacht
DATA=/var/lib/znacht
ENVFILE=/etc/znacht/env
export UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 UV_PYTHON_INSTALL_DIR=/opt/uv/python

apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq git curl ca-certificates >/dev/null

id znacht >/dev/null 2>&1 || useradd --system --home-dir "$DATA" --shell /usr/sbin/nologin znacht
install -d -m 750 -o znacht -g znacht "$DATA"
install -d -m 750 -o root -g znacht /etc/znacht

command -v uv >/dev/null 2>&1 || curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null

if [ -d "$APP/.git" ]; then
  git -C "$APP" fetch -q origin "$BRANCH"
  git -C "$APP" checkout -q "$BRANCH"
  git -C "$APP" pull -q --ff-only
else
  git clone -q --branch "$BRANCH" "$REPO" "$APP"
fi

cd "$APP"
uv python install 3.12 -q
UV_COMPILE_BYTECODE=1 uv sync -q --all-packages --no-dev --frozen --python 3.12
chmod -R o+rX /opt/uv

cat > /etc/systemd/system/znacht.service <<EOF
[Unit]
Description=Znacht engine
After=network-online.target
Wants=network-online.target
ConditionPathExists=$ENVFILE

[Service]
User=znacht
Group=znacht
WorkingDirectory=$APP
Environment=HOME=$DATA
Environment=UV_CACHE_DIR=$DATA/.cache/uv
Environment=UV_PYTHON_INSTALL_DIR=/opt/uv/python
Environment=ZNACHT_DATA_DIR=$DATA
Environment=ZNACHT_HOUSEHOLD=$DATA/household.yaml
Environment=ZNACHT_COOKIDOO_TOKEN_FILE=$DATA/cookidoo-token.json
Environment=ZNACHT_MIGROS_SESSION_FILE=$DATA/migros-session.json
ExecStart=/usr/local/bin/uv run --frozen --no-sync --env-file $ENVFILE znacht-engine
Restart=on-failure
RestartSec=5
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
ReadWritePaths=$DATA

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable -q znacht
if [ -f "$ENVFILE" ]; then
  systemctl restart znacht
  echo "znacht updated and restarted"
else
  echo "znacht installed; it starts once $ENVFILE exists (deploy/lxc/restore.sh puts it there)"
fi
