import re
import sys
import urllib.request

BASE = "https://traininfo.jr-central.co.jp/zairaisen/"

scripts = [
    "js/common.js",
    "js/const.js",
    "js/contents.js",
    "js/dateTime.js",
    "js/lang.js",
    "js/status.js",
    "js/train_information.js",
]

def print_function_block(text: str, name: str) -> None:
    marker = f"const {name}"
    idx = text.find(marker)
    if idx < 0:
        print(f"\n=== {name}: not found ===")
        return

    next_idx = text.find("\nconst ", idx + 50)

    if next_idx < 0:
        next_idx = len(text)

    print(f"\n=== function {name} ===")
    print(text[idx:next_idx])

for s in scripts:
    url = BASE + s

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept-Language": "ja,en-US;q=0.9",
        },
    )

    text = urllib.request.urlopen(req, timeout=15).read().decode(
        "utf-8", errors="replace"
    )

    if s == "js/contents.js":
        for function_name in [
            "getServiceStatus",
            "getLineMasters",
            "getOperationStatus",
            "getTransPatterns",
            "getAllLinesNoticeInfo",
            "getNoticeInfo",
        ]:
            print_function_block(text, function_name)

    if s == "js/const.js":
        print("\n=== const.js important constants ===")
        for const_name in [
            "SERVICE_STATUS_PATH",
            "LINE_MASTER_PATH",
            "OPERATION_PATH",
            "OPERATION_HISTORY_PATH",
            "NOTICE_PATH",
            "NOTICE_HISTORY_PATH",
            "TRANS_PATTERN_PATH",
            "conversionLineParam",
        ]:
            idx = text.find(const_name)
            if idx >= 0:
                print(f"\n--- {const_name} ---")
                print(text[max(0, idx - 300): idx + 1200])

    print("\n===", s, "===")

    keys = [
        ".json",
        "getJSON",
        "$.ajax",
        "$.get",
        "fetch(",
        "service",
        "history",
        "status",
        "message",
        "info",
        "line=",
        "url",
        "data/",
        "api",
        "const getOperationStatus",
        "const getServiceStatus",
        "const getLineMasters",
        "const getNoticeInfo",
        "const getAllLinesNoticeInfo",
        "const getTransPatterns",
        "OPERATION",
        "OPERATION_STATUS",
        "STATUS_PATH",
        "LINE_MASTER_PATH",
        "SERVICE_STATUS",
        "SERVICE_STATUS_PATH",
        "getOperationStatus =",
        "getServiceStatus =",
        "getLineMasters =",
        "getNoticeInfo =",
        "getAllLinesNoticeInfo =",
        "getTransPatterns =",
        "operationStatuses",
        "OPERATION_PATH",
        "NOTICE_PATH",
        "TRANS_PATTERN_PATH",
        "LINE_MASTER_PATH",
        "STATION_MASTER_PATH",
    ]

    for key in keys:
        if key.lower() in text.lower():
            print("hit:", key)

    json_paths = sorted(set(re.findall(r'["\']([^"\']+\.json)', text, re.I)))
    if json_paths:
        print("json paths:")
        for path in json_paths:
            print(" -", path)

    for key in keys:
        lower = text.lower()
        start = 0
        shown = 0
        while shown < 3:
            idx = lower.find(key.lower(), start)
            if idx < 0:
                break
            print(f"\n--- around {key} ---")
            print(text[max(0, idx - 500): idx + 1200])
            start = idx + len(key)
            shown += 1

    print("\n=== const/function candidates ===")
    for pattern in [
        r"const\s+\w+\s*=\s*\([^)]*\)\s*=>",
        r"const\s+\w+\s*=\s*async\s*\([^)]*\)\s*=>",
        r"function\s+\w+\s*\([^)]*\)",
        r"[A-Z0-9_]+_PATH\s*=",
        r"[A-Z0-9_]+\s*=\s*['\"]",
        r"const\s+getOperationStatus\s*=",
        r"const\s+getServiceStatus\s*=",
        r"const\s+getLineMasters\s*=",
        r"const\s+getNoticeInfo\s*=",
        r"const\s+getAllLinesNoticeInfo\s*=",
        r"const\s+getTransPatterns\s*=",
    ]:
        for match in re.finditer(pattern, text):
            idx = match.start()
            snippet = text[max(0, idx - 500): idx + 1500]
            if any(word in snippet for word in [
                "Operation", "Status", "Notice", "Line", "SERVICE", "STATUS", "PATH", "json", "senku", "unkou"
            ]):
                print("\n--- candidate ---")
                print(snippet)