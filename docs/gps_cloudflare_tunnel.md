# GPS Web App Cloudflare Tunnel

GPS Web mini app はブラウザの Geolocation API を使うため、メンバー利用時は HTTPS 公開URLが必要。
Oracle側で外部HTTPポートは開けず、アプリは `127.0.0.1:8787` で待受し、Cloudflare Tunnel で HTTPS URLへ中継する。

本運用は quick tunnel ではなく、Cloudflare named tunnel と固定URLで運用する。

## 1. cloudflared インストール

Ubuntu:

```bash
cd /tmp
wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
sudo dpkg -i cloudflared-linux-amd64.deb
cloudflared --version
```

## 2. 一時URLテスト

named tunnel 作成前の疎通確認だけに使う。

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

`https://xxxxx.trycloudflare.com` のようなURLが表示される。
このURLは再起動で変わるため、本運用の `GPS_WEB_BASE_URL` には使わない。

## 3. named tunnel 作成

Cloudflareにログイン:

```bash
cloudflared tunnel login
```

tunnel作成:

```bash
cloudflared tunnel create nagoya-gps
```

固定ホスト名をCloudflare DNSへ登録:

```bash
cloudflared tunnel route dns nagoya-gps gps.<domain>
```

`~/.cloudflared/config.yml`:

```yaml
tunnel: nagoya-gps
credentials-file: /home/ubuntu/.cloudflared/<TUNNEL_ID>.json

ingress:
  - hostname: gps.<domain>
    service: http://127.0.0.1:8787
  - service: http_status:404
```

起動確認:

```bash
cloudflared tunnel run nagoya-gps
```

別ターミナルで確認:

```bash
curl https://gps.<domain>/gps
```

## 4. systemd化

GPS Web app:

```ini
# /etc/systemd/system/gps-web-app.service
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
```

Cloudflare Tunnel:

```ini
# /etc/systemd/system/gps-cloudflared.service
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
```

このリポジトリの導入スクリプトでも配置できる。

```bash
cd /home/ubuntu/nagoya_event
sudo bash scripts/install_gps_systemd.sh
```

手動で有効化する場合:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now gps-web-app.service
sudo systemctl enable --now gps-cloudflared.service
sudo systemctl status gps-web-app.service
sudo systemctl status gps-cloudflared.service
```

ログ確認:

```bash
journalctl -u gps-web-app.service -f
journalctl -u gps-cloudflared.service -f
```

## 5. .env 設定例

ローカル `.env` と Ubuntu 本番環境 `/home/ubuntu/nagoya_event/.env` の両方に必要。

```bash
YAHOO_CLIENT_ID=...
YAHOO_PLACEINFO_TEST_CHANNEL_ID=1521532870601080852
GPS_WEB_BASE_URL=https://gps.<domain>
GPS_REPORT_CHANNEL_ID=1521532870601080852
```

`GPS_WEB_BASE_URL` は末尾 `/gps` なしで設定する。ボタン投稿側で `/gps` を付与する。

反映後、DiscordのURLボタンを再投稿する。

```bash
cd /home/ubuntu/nagoya_event
source .venv/bin/activate
python3 tools/location/post_placeinfo_test_button.py --force
```
