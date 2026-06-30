#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "sudoで実行してください: sudo bash scripts/install_gps_systemd.sh" >&2
  exit 1
fi

cat >/etc/systemd/system/gps-web-app.service <<'SERVICE'
[Unit]
Description=Nagoya Event GPS Web App
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/nagoya_event
ExecStart=/home/ubuntu/nagoya_event/scripts/start_gps_web_app.sh
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SERVICE

cat >/etc/systemd/system/gps-cloudflared.service <<'SERVICE'
[Unit]
Description=Cloudflare Tunnel for GPS Web App
After=network.target gps-web-app.service
Requires=gps-web-app.service

[Service]
User=ubuntu
ExecStart=/usr/bin/cloudflared tunnel run nagoya-gps
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
systemctl enable gps-web-app.service
systemctl enable gps-cloudflared.service
systemctl start gps-web-app.service
systemctl start gps-cloudflared.service

echo "GPS systemd services installed and started."
