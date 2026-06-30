#!/usr/bin/env bash
set -euo pipefail

cd /home/ubuntu/nagoya_event
source .venv/bin/activate
python3 tools/location/gps_web_app.py --host 127.0.0.1 --port 8787
