#!/usr/bin/env bash
set -euo pipefail

cloudflared tunnel --url http://127.0.0.1:8787
