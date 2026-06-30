# GPS Web App Tailscale Funnel

GPS Web mini app の本番公開は Tailscale Funnel を推奨する。
Oracle側で80/443を開けず、NginxやCertbotも使わない。

前提:

- Ubuntu Tailscale IP: `100.81.54.84`
- GPS Web App: `127.0.0.1:8787`
- 公開URL: `https://<hostname>.<tailnet>.ts.net`

## 1. GPS Web App 起動

```bash
cd /home/ubuntu/nagoya_event
bash scripts/start_gps_web_app.sh
```

ローカル確認:

```bash
curl http://127.0.0.1:8787/gps
```

## 2. Funnel 有効化

```bash
sudo tailscale funnel 8787
```

確認:

```bash
tailscale funnel status
```

期待出力:

```text
https://<hostname>.<tailnet>.ts.net
└─ proxy http://127.0.0.1:8787
```

詳細確認:

```bash
tailscale serve status
```

## 3. .env

ローカル `.env` と Ubuntu 本番環境 `/home/ubuntu/nagoya_event/.env` の両方に必要。

```bash
GPS_WEB_BASE_URL=https://<hostname>.<tailnet>.ts.net
GPS_REPORT_CHANNEL_ID=1521532870601080852
```

`GPS_WEB_BASE_URL` は末尾 `/gps` なしで設定する。Discord URLボタン側で `/gps` を付与する。

反映後、DiscordのURLボタンを再投稿する。

```bash
cd /home/ubuntu/nagoya_event
source .venv/bin/activate
python3 tools/location/post_placeinfo_test_button.py --force
```

## 4. 運用メモ

Cloudflare Tunnel は開発用として残す。
本番は Tailscale Funnel の `*.ts.net` 固定URLを `GPS_WEB_BASE_URL` に設定する。
