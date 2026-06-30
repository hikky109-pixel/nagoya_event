# GPS Web App Cloudflare Tunnel

GPS Web mini app はブラウザの Geolocation API を使うため、メンバー利用時は HTTPS 公開URLが必要。
Oracle側で外部HTTPポートは開けず、アプリは `127.0.0.1:8787` で待受し、Cloudflare Tunnel で HTTPS URLへ中継する。

## 1. cloudflared インストール

Ubuntu:

```bash
cd /tmp
wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
sudo dpkg -i cloudflared-linux-amd64.deb
cloudflared --version
```

## 2. 一時URLテスト

ターミナル1:

```bash
cd /home/ubuntu/nagoya_event
bash scripts/start_gps_web_app.sh
```

ターミナル2:

```bash
cd /home/ubuntu/nagoya_event
bash scripts/start_gps_tunnel.sh
```

`https://xxxxx.trycloudflare.com` のようなURLが表示されたら、`.env` に設定する。

```bash
GPS_WEB_BASE_URL=https://xxxxx.trycloudflare.com
GPS_REPORT_CHANNEL_ID=1521532870601080852
```

反映後、DiscordのURLボタンを再投稿する。

```bash
cd /home/ubuntu/nagoya_event
source .venv/bin/activate
python3 tools/location/post_placeinfo_test_button.py --force
```

## 3. systemd化

GPS Web app:

```ini
# /etc/systemd/system/nagoya-gps-web.service
[Unit]
Description=Nagoya GPS Web App
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/nagoya_event
ExecStart=/home/ubuntu/nagoya_event/scripts/start_gps_web_app.sh
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Cloudflare Tunnel:

```ini
# /etc/systemd/system/nagoya-gps-tunnel.service
[Unit]
Description=Nagoya GPS Web App Cloudflare Tunnel
After=network-online.target nagoya-gps-web.service
Wants=network-online.target nagoya-gps-web.service

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/nagoya_event
ExecStart=/home/ubuntu/nagoya_event/scripts/start_gps_tunnel.sh
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

有効化:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now nagoya-gps-web.service
sudo systemctl enable --now nagoya-gps-tunnel.service
sudo systemctl status nagoya-gps-web.service
sudo systemctl status nagoya-gps-tunnel.service
```

ログ確認:

```bash
journalctl -u nagoya-gps-web.service -f
journalctl -u nagoya-gps-tunnel.service -f
```

## 4. .env 設定例

ローカル `.env` と Ubuntu 本番環境 `/home/ubuntu/nagoya_event/.env` の両方に必要。

```bash
YAHOO_CLIENT_ID=...
YAHOO_PLACEINFO_TEST_CHANNEL_ID=1521532870601080852
GPS_WEB_BASE_URL=https://xxxxx.trycloudflare.com
GPS_REPORT_CHANNEL_ID=1521532870601080852
```

`GPS_WEB_BASE_URL` は末尾 `/gps` なしで設定する。ボタン投稿側で `/gps` を付与する。
