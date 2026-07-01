# JMA Warning Level Equivalent API Research

調査日: 2026-07-02

対象ページ:

- https://www.jma.go.jp/bosai/warning/#area_type=class20s&area_code=2310000

## 結論

JMAの警報・注意報ページで表示される「警戒レベル相当情報」は、既存実装で使っていた通常JSONだけでは不足する。

既存:

- https://www.jma.go.jp/bosai/warning/data/warning/230000.json

このJSONは名古屋市 `2310000` の通常の警報・注意報一覧として使えるが、スクショ上段の「警戒レベル相当情報」に出る以下は十分に取れない。

- 大雨注意報の警戒レベル相当
- 土砂災害注意報の警戒レベル相当
- 指定河川洪水予報のレベル2氾濫注意情報

ページが実際に参照している主なJSONは以下。

- https://www.jma.go.jp/bosai/warning/data/r8/230000.json
- https://www.jma.go.jp/bosai/flood/data/r8/flood_xml.json
- https://www.jma.go.jp/bosai/warning_timeline/data/230000.json
- https://www.jma.go.jp/bosai/common/const/area.json

実通知でまず使うべきなのは `warning/data/r8/230000.json` と `flood/data/r8/flood_xml.json`。

## area_code

名古屋市:

- `class20s`: `2310000`
- `area.json` 上の name: `名古屋市`
- parent: `230011` / `尾張東部`
- office: `230000` / 愛知県

JMAページは `area_type=class20s&area_code=2310000` の場合でも、内部では office code `230000` に変換して以下を読む。

```text
./warning/data/r8/230000.json
../warning_timeline/data/230000.json
../flood/data/r8/flood_xml.json
```

## 1. 警戒レベル相当情報

URL:

```text
https://www.jma.go.jp/bosai/warning/data/r8/230000.json
```

レスポンスは配列。各要素に発表単位の `warning.class20Items` がある。

名古屋市で絞るキー:

```python
for doc in data:
    for item in doc["warning"]["class20Items"]:
        if item["areaCode"] == "2310000":
            ...
```

2026-07-02調査時点で、名古屋市には以下が入っていた。

```json
{
  "areaCode": "2310000",
  "kinds": [
    {
      "code": "10",
      "status": "継続",
      "properties": [
        {
          "type": "大雨浸水危険度",
          "significancyPart": {
            "locals": [
              {
                "code": "21"
              }
            ]
          }
        }
      ]
    }
  ]
}
```

```json
{
  "areaCode": "2310000",
  "kinds": [
    {
      "code": "29",
      "status": "継続",
      "properties": [
        {
          "type": "土砂災害危険度",
          "significancyPart": {
            "locals": [
              {
                "code": "21"
              }
            ]
          }
        }
      ]
    }
  ]
}
```

読み取り候補:

- `kind.code == "10"`: 大雨注意報
- `kind.code == "29"`: 土砂災害注意報相当
- `kind.status`: `発表` / `継続` / `解除` など
- `kind.properties[].type`: `大雨浸水危険度`, `土砂災害危険度`, `雷危険度` など
- `kind.properties[].significancyPart.locals[].code`: 警戒レベル/危険度コード

調査時点の名古屋市:

- 大雨: `code=10`, `status=継続`, `type=大雨浸水危険度`, `significancyPart.locals[0].code=21`
- 土砂災害: `code=29`, `status=継続`, `type=土砂災害危険度`, `significancyPart.locals[0].code=21`
- 雷: `code=14`, `status=発表`, `type=雷危険度`, `significancyPart.locals[0].code=20`

スクショの「レベル2 大雨注意報」「レベル2 土砂災害注意報」は、この `significancyPart` から作られている可能性が高い。

## 2. 指定河川洪水予報 / 氾濫注意情報

URL:

```text
https://www.jma.go.jp/bosai/flood/data/r8/flood_xml.json
```

レスポンスは全国の指定河川洪水予報の配列。名古屋市で絞るキー:

```python
matched = [
    item for item in data
    if "2310000" in item.get("class20Codes", [])
]
```

2026-07-02調査時点で、名古屋市 `2310000` に該当する氾濫注意情報が2件あった。

```json
{
  "status": "通常",
  "reportDatetime": "2026-07-02T04:50:00+09:00",
  "infoType": "発表",
  "riverName": "愛知県日光川水系　日光川",
  "riverCode": "230054000100",
  "class20Codes": [
    "2310000"
  ],
  "item": {
    "name": "レベル２氾濫注意報",
    "code": "20",
    "condition": "レベル２氾濫注意報（発表）"
  }
}
```

```json
{
  "status": "通常",
  "reportDatetime": "2026-07-02T07:00:00+09:00",
  "infoType": "発表",
  "riverName": "庄内川",
  "riverCode": "850508000100",
  "class20Codes": [
    "2310000"
  ],
  "item": {
    "name": "レベル２氾濫注意報",
    "code": "20",
    "condition": "レベル２氾濫注意報（発表）"
  }
}
```

必要キー:

- `class20Codes`: 市区町村コード。名古屋市は `2310000`
- `riverName`: 河川名
- `riverCode`: 河川コード
- `item.name`: 例 `レベル２氾濫注意報`
- `item.code`: 例 `20`
- `item.condition`: 例 `レベル２氾濫注意報（発表）`
- `infoType`: `発表` など
- `reportDatetime`

スクショの「愛知県日光川水系 日光川 レベル2氾濫注意情報」はこのJSONから取得できる。

## 3. 土砂災害警戒情報 / 注意情報

名古屋市のスクショに出ている「レベル2 土砂災害注意報」は `warning/data/r8/230000.json` 側で取得できる。

キー:

- `warning.class20Items[].areaCode == "2310000"`
- `kinds[].code == "29"`
- `kinds[].properties[].type == "土砂災害危険度"`
- `significancyPart.locals[].code == "21"`

`information/data/information.json` も調査したが、これは府県気象情報・地方気象情報などの一覧で、今回スクショ上段の警戒レベル相当表の主データではなさそう。

## 4. 高潮

スクショ上段には高潮列がある。ページJSは `warning/data/r8/230000.json` と以下の定数を参照している。

```text
https://www.jma.go.jp/bosai/warning/const/no_wave_tide.json
https://www.jma.go.jp/bosai/warning/const/with_tidal_area.json
```

高潮の発表がある場合は `warning/data/r8/230000.json` の `class20Items[].kinds[]` に通常の警報・注意報コードとして入る想定。

既知コード:

- `08`: 高潮警報
- `19`: 高潮注意報

ただし調査時点の名古屋市には高潮の発表がなかったため、実レスポンスで `properties[].type` がどう出るかは未確認。実装時は `code in {"08", "19"}` を見るのが第一候補。

## 5. 時系列データ

URL:

```text
https://www.jma.go.jp/bosai/warning_timeline/data/230000.json
```

これは発表状態そのものより、今後の危険度・予想雨量・風などの時間推移を見る用途。

名古屋市 `2310000` の例:

```json
{
  "areaCode": "2310000",
  "kinds": [
    {
      "status": "発表",
      "dateTime": "2026-07-02T04:55:00+09:00",
      "significancyParts": [
        {
          "type": "大雨浸水危険度",
          "locals": [
            {
              "codes": [
                "21",
                "11"
              ]
            }
          ]
        }
      ]
    },
    {
      "forecastParts": [
        {
          "type": "１時間最大雨量",
          "locals": [
            {
              "values": [
                {
                  "unit": "mm",
                  "value": "30"
                }
              ]
            }
          ]
        }
      ]
    }
  ]
}
```

実装優先度は低め。将来「今後何時間続くか」「1時間最大雨量」などを出したい場合に使える。

## 確認コマンド

```bash
curl -s 'https://www.jma.go.jp/bosai/warning/data/r8/230000.json' \
  | python3 -m json.tool | head -100
```

```bash
curl -s 'https://www.jma.go.jp/bosai/flood/data/r8/flood_xml.json' \
  | python3 -m json.tool | head -100
```

```bash
curl -s 'https://www.jma.go.jp/bosai/warning_timeline/data/230000.json' \
  | python3 -m json.tool | head -100
```

名古屋市のみ抽出:

```python
import json
import urllib.request

def fetch(url):
    with urllib.request.urlopen(url, timeout=20) as response:
        return json.loads(response.read().decode())

warning = fetch("https://www.jma.go.jp/bosai/warning/data/r8/230000.json")
for doc in warning:
    for item in doc.get("warning", {}).get("class20Items", []):
        if item.get("areaCode") == "2310000":
            print(doc.get("reportDatetime"), item.get("kinds", []))

flood = fetch("https://www.jma.go.jp/bosai/flood/data/r8/flood_xml.json")
for item in flood:
    if "2310000" in [str(code) for code in item.get("class20Codes", [])]:
        print(item.get("riverName"), item.get("item", {}))
```

## 実装メモ

次の実装では、JMA状態管理の入力を以下に切り替える。

1. `warning/data/r8/230000.json`
   - `class20Items[].areaCode == "2310000"`
   - `kinds[].code in {"03","04","05","08","10","14","15","18","19","29"}`
   - `status in {"発表","継続"}` を active とする
   - `status == "解除"` は解除候補
2. `flood/data/r8/flood_xml.json`
   - `"2310000" in class20Codes`
   - `item.name` / `item.condition` に `氾濫注意報`, `氾濫警戒情報` などがあるものを active とする
3. `weather_state.json` の `jma.active` のキーは、通常警報注意報と河川を分ける。
   - `warning:2310000:10`
   - `warning:2310000:29`
   - `flood:230054000100:20`

## 注意点

- `warning/data/warning/230000.json` と `warning/data/r8/230000.json` は別物。後者に警戒レベル相当の `properties.significancyPart` が入る。
- `flood_xml.json` は全国配列なので、必ず `class20Codes` で名古屋市を絞る。
- `warning_timeline/data/230000.json` は通知トリガーよりも補足情報向き。
- JMAページは相対URLを使っているので、実URLは `https://www.jma.go.jp/bosai/` を基点に解決する。
