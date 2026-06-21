import os

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

# Webhook版を使う場合のみ環境変数で設定。
GEMMA_DISCORD_WEBHOOK = os.getenv("GEMMA_DISCORD_WEBHOOK", "")
GEMMA_WEBHOOK_URL = os.getenv("GEMMA_WEBHOOK_URL", "")

GEMMA_CHANNELS = {
    "main": os.getenv("GEMMA_CHANNEL_MAIN", ""),
    "railway": os.getenv("GEMMA_CHANNEL_RAILWAY", ""),
    "road": os.getenv("GEMMA_CHANNEL_ROAD", ""),
    "event": os.getenv("GEMMA_CHANNEL_EVENT", ""),
    "nagoya": os.getenv("GEMMA_CHANNEL_NAGOYA", ""),
    "food": os.getenv("GEMMA_CHANNEL_FOOD", ""),
}
