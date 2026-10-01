#!/bin/sh
set -eu
if [ "$(id -u)" -ne 0 ]; then
  echo 'Run as root' >&2
  exit 1
fi
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
apt-get update
apt-get install -y python3-venv rsync openssh-client
id chata-worker >/dev/null 2>&1 || useradd --system --create-home --home-dir /var/lib/chata-worker --shell /usr/sbin/nologin chata-worker
install -d -o chata-worker -g chata-worker -m 0700 /var/lib/chata-worker/.ssh
install -d -m 0755 /opt/chata /etc/chata-worker
tar --exclude=.venv --exclude=.git -C "$project_dir" -cf - . | tar -C /opt/chata -xf -
python3 -m venv /opt/chata/.venv
/opt/chata/.venv/bin/pip install --requirement /opt/chata/worker/requirements.txt
if [ ! -f /etc/chata-worker/config.json ]; then
  install -m 0640 -o root -g chata-worker /opt/chata/worker/config.example.json /etc/chata-worker/config.json
fi
install -m 0644 /opt/chata/worker/chata-worker.service /etc/systemd/system/chata-worker.service
install -m 0644 /opt/chata/worker/chata-worker.timer /etc/systemd/system/chata-worker.timer
systemctl daemon-reload
systemctl enable --now chata-worker.timer
