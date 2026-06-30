import os
try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv():
        env_path = ".env"
        if not os.path.exists(env_path):
            return False
        try:
            with open(env_path, encoding="utf-8") as f:
                lines = f.readlines()
        except OSError:
            return False
        loaded = False
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            key = key.strip()
            if not key or key in os.environ:
                continue
            os.environ[key] = value.strip().strip('"').strip("'")
            loaded = True
        return loaded

load_dotenv()

def _int_env(name, default):
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _bool_env(name, default):
    value = os.getenv(name, "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


def _channel_id_env(name):
    value = os.getenv(name, "").strip()
    if value.startswith("<") and value.endswith(">"):
        value = value[1:-1].strip()
    return value

# ==========================
# 名古屋イベントBOT 共通設定
# ==========================

WANTED_VENUES = [

    # ----------------------
    # 大型会場
    # ----------------------

    "バンテリンドームナゴヤ",
    "IGアリーナ",

    "日本ガイシホール",
    "クロコくんホール",

    "ポートメッセなごや",

    "愛知スカイエキスポ",
    "Aichi Sky Expo",

    "パロマ瑞穂スタジアム",

    # ----------------------
    # 音楽ホール
    # ----------------------

    "Zepp Nagoya",

    "DIAMOND HALL",
    "ダイヤモンドホール",
    "ダイアモンドホール",

    "COMTEC PORTBASE",
    "ポートベース",

    # ----------------------
    # 文化施設
    # ----------------------

    "愛知県芸術劇場",
    
    "中日ホール",
    
    "Niterra日本特殊陶業市民会館フォレストホール",
    "Niterra日本特殊陶業市民会館",

    "岡谷鋼機名古屋公会堂",
    "名古屋公会堂",

    "御園座",

    "吹上ホール",

    # ----------------------
    # 野外
    # ----------------------

    "モリコロパーク",
    "愛・地球博記念公園",

    "大高緑地",

    # ----------------------
    # その他
    # ----------------------

    "SAKAE SP-RING",
    "栄スプリング",
]

# ==========================
# ジェンマ課長 Discord Bot API設定
# ==========================
# Bot TokenはGit管理に載せない運用。
# 環境変数で設定してください。
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
DISCORD_BOT_ID = os.getenv("DISCORD_BOT_ID", "1518154055455871036")
GEMMA_DISCORD_CHANNEL_ID = os.getenv("GEMMA_DISCORD_CHANNEL_ID", "")
GEMMA_GUILD_ID = os.getenv("GEMMA_GUILD_ID", "")
GEMMA_CHANNEL_TEST = os.getenv("GEMMA_CHANNEL_TEST", "")
GEMMA_CHANNEL_ADMIN = os.getenv("GEMMA_CHANNEL_ADMIN", "")
GEMMA_CHANNEL_NAGOYA = _channel_id_env("GEMMA_CHANNEL_NAGOYA")
GEMMA_CHANNEL_RAILWAY = _channel_id_env("GEMMA_CHANNEL_RAILWAY")
WEATHER_ALERT_CHANNEL_ID = _channel_id_env("WEATHER_ALERT_CHANNEL_ID") or None
YAHOO_CLIENT_ID = os.getenv("YAHOO_CLIENT_ID", "").strip() or None
YAHOO_PLACEINFO_TEST_CHANNEL_ID = _channel_id_env("YAHOO_PLACEINFO_TEST_CHANNEL_ID") or None

# Webhook版を使う場合のみ環境変数で設定。
GEMMA_DISCORD_WEBHOOK = os.getenv("GEMMA_DISCORD_WEBHOOK", "")
GEMMA_WEBHOOK_URL = os.getenv("GEMMA_WEBHOOK_URL", "")

GEMMA_CHANNELS = {
    "main": os.getenv("GEMMA_CHANNEL_MAIN", ""),
    "railway": GEMMA_CHANNEL_RAILWAY,
    "road": os.getenv("GEMMA_CHANNEL_ROAD", ""),
    "event": os.getenv("GEMMA_CHANNEL_EVENT", ""),
    "nagoya": GEMMA_CHANNEL_NAGOYA,
    "food": os.getenv("GEMMA_CHANNEL_FOOD", ""),
}

# ==========================
# ジェンマ課長 CPU高速化設定
# ==========================
# プロンプトへ投入する会話履歴と検索候補を絞り、CPU環境での応答待ちを減らす。
GEMMA_CHAT_HISTORY_LIMIT = _int_env("GEMMA_CHAT_HISTORY_LIMIT", 20)
GEMMA_HISTORY_SEARCH_MAX_ITEMS = _int_env("GEMMA_HISTORY_SEARCH_MAX_ITEMS", 12)
GEMMA_ORACLE_MAX_ITEMS = _int_env("GEMMA_ORACLE_MAX_ITEMS", 3)
GEMMA_TIME_DEBUG = _bool_env("GEMMA_TIME_DEBUG", True)
GEMMA_SEARCH_HISTORY_OLLAMA_TIMEOUT = _int_env("GEMMA_SEARCH_HISTORY_OLLAMA_TIMEOUT", 35)
AI_MODEL = os.getenv("AI_MODEL", "qwen").strip() or "qwen"
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma3:4b").strip() or "gemma3:4b"
