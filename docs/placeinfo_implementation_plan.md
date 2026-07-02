# Yahoo PlaceInfo 地名ラベル実装計画

作成日: 2026-07-03

目的は、繁忙ボタンの GPS 座標から「タクシー運転手が1秒で理解できる地名ラベル」を生成すること。個人情報、乗務員情報、売上情報は扱わず、蓄積対象は繁忙地点と補正済みラベルだけに限定する。

最終出力の目標:

- `錦3丁目 袋町通繁忙`
- `錦3丁目 袋町通（ローソン錦袋町通店前）繁忙`
- `栄4丁目 池田公園付近繁忙`
- `錦通大津（サンシャイン栄付近）繁忙`
- `東雲橋西交差点付近繁忙`

## 参照した情報

- `tools/location/get_yahoo_placeinfo.py`
- `tools/location/gps_web_app.py`
- `tools/location/placeinfo_test_buttons.py`
- `data/location/placeinfo/*.json`
- Discord 履歴: `data/ai/discord_history/*.jsonl`
- Yahoo!デベロッパーネットワーク 場所情報API: https://developer.yahoo.co.jp/webapi/map/openlocalplatform/v1/placeinfo.html
- 位置確認用の公開地点情報: NAVITIME / Yahoo!マップ / MapFan

共有済み PDF はリポジトリ内では確認できなかったため、API仕様は公式Webドキュメントと実レスポンスを優先した。

## 現状実装

`get_yahoo_placeinfo.py` は以下のクエリで PlaceInfo API を呼んでいる。

```text
https://map.yahooapis.jp/placeinfo/V1/get
appid=<YAHOO_CLIENT_ID>
lat=<lat>
lon=<lon>
output=json
```

現状の `extract_candidates()` は `ResultSet.Result` と `ResultSet.Area` から `name` と `address` だけを抽出している。実際には raw JSON に `Category`, `Score`, `Uid`, `Where`, `Label`, `Roadname`, `Address`, `Area.Type` が含まれるため、現状実装は判断材料をかなり捨てている。

まずは抽出モデルを広げるべき。

```python
{
    "name": feature.get("Name"),
    "label": feature.get("Label"),
    "category": feature.get("Category"),
    "where": feature.get("Where"),
    "combined": feature.get("Combined"),
    "score": float(feature.get("Score") or 0),
    "uid": feature.get("Uid"),
}
```

## APIレスポンス分析

公式仕様と実レスポンスから確認できた主な項目:

| 項目 | 内容 | ラベル生成での用途 |
| --- | --- | --- |
| `ResultSet.Address` | 住所配列。例: `愛知県`, `名古屋市中区`, `錦`, `３丁目`, `１７` | `錦3丁目`, `栄4丁目` の町名ベース |
| `ResultSet.Roadname` | 近くの道路名。null のことも多い | 出れば最優先候補 |
| `ResultSet.Area` | エリア/大規模施設のリスト | 栄、名駅、SUNSHINE SAKAE など |
| `Area.Type` | `1` 大規模施設、`2` エリア | 大型施設と地名エリアの区別 |
| `ResultSet.Result` | 周辺施設リスト | 交差点、店舗、ホテル、コンビニなど |
| `Result.Name/Label` | 施設名 | 表示候補 |
| `Result.Category` | 施設カテゴリ | 交差点/コンビニ/ホテル/地下街除外の判定 |
| `Result.Where` | 表示用場所名 | `東栄通の...` のように通り名が入る場合あり |
| `Result.Combined` | 表示用文字列 | デバッグと暫定表示に有用 |
| `Result.Uid` | 施設UID | 秘伝のタレDBのキー候補 |
| `Score` | スコア。公式説明では大きいほど確度が高い | 距離そのものではなく候補順位の補助 |

距離フィールドは実レスポンスにも公式項目にも見当たらなかった。`Score` は距離メートルではなく、近さ、施設の代表性、データ側の信頼度が混ざった確度と見るべき。例えば錦通大津では `すき家サカエチカ店` が `99.52`、`SUNSHINE SAKAE` が `89.81`、`錦通大津交差点` が `49.99` で、タクシー目線の正解順位とは一致しない。

通り名は `Roadname` または `Where` で取れる場合がある。池田公園付近では `Roadname=東栄通`、候補の `Where=東栄通` が確認できた。一方、錦内部の袋町通、七間町通、伊勢町通付近では `Roadname=null` になりやすい。したがって錦内部の通り名は Yahoo 単独では不十分で、座標ポリゴンまたは手動DBが必要。

交差点は `Category=地点名` かつ `Name` が `...交差点` の形で出る。郊外サンプルでは非常に強い。

カテゴリ情報はある。特に以下が実装上使える。

- `地点名`: 交差点候補
- `ローソン`, `ファミリーマート`, `デイリーヤマザキ`, `セブン-イレブン`: コンビニ補助
- `ホテル`, `ビジネスホテル`: 目印として中程度に有効
- `ショッピングセンター・モール、複合商業施設`: 大型ランドマーク
- `大型専門店...`, `飲食店`, `地下街名入り店舗`: 除外/降格候補

## 実測ログ分析

### 名駅

保存ログ:

- `data/location/placeinfo/20260701_023818_gps.json`
- `data/location/placeinfo/20260701_023819_gps_discord.json`
- `data/location/placeinfo/20260703_050111_meieki_existing.json`

座標: `35.170915, 136.881537`

上位候補:

- ファッションワン
- amanoJR名駅中央店
- ハンズ名古屋店
- 名古屋駅（名古屋市営地下鉄）
- 名古屋駅（JR）

考察:

名駅は駅・地下街・商業施設が強い。繁忙通知では `ファッションワン前` より `名駅1丁目`、`名駅中央`, `名駅地下`, `JR名古屋駅付近` のようなタクシー目線の再ラベル化が必要。地下/構内店舗が上位に出やすく、PlaceInfoそのままは危険。

### 栄4丁目 / 池田公園付近

保存ログ:

- `data/location/placeinfo/20260703_050110_ikeda_park.json`

座標: `35.166337, 136.912610`

API結果:

- `Address`: 愛知県 / 名古屋市中区 / 栄 / ４丁目 / １８
- `Roadname`: 東栄通
- 上位候補: やよい軒栄四丁目店、アパホテル名古屋栄、スマイルホテル名古屋栄、ローソンストア100栄五丁目店

考察:

ユーザー正解例は `栄4丁目 池田公園付近`。Yahoo は東栄通とホテル/店舗を返すが、池田公園そのものは候補に出なかった。池田公園は Yahoo だけではなく秘伝のタレDBで固定ラベル化する必要がある。

### 錦通大津 / サンシャイン栄付近

保存ログ:

- `data/location/placeinfo/20260703_050110_nishiki_odori_otsu.json`

座標: `35.169973, 136.906720`

API結果:

- `Address`: 愛知県 / 名古屋市中区 / 錦 / ３丁目 / １７
- `Roadname`: null
- `Area`: 栄, SUNSHINE SAKAE, 久屋大通
- 上位候補: すき家サカエチカ店, SUNSHINE SAKAE, SUIT SELECT, 石井スポーツ, 牛角
- 交差点: 錦通大津交差点が6位

考察:

地下街/ビル内/店舗が上位に混ざる典型例。タクシー目線では `すき家サカエチカ店付近` より `錦通大津（サンシャイン栄付近）` が正しい。除外ロジックと Sランクランドマーク昇格が必要。

### 東雲橋西

保存ログ:

- `data/location/placeinfo/20260703_050110_shinonomebashi_west.json`

座標: `35.146791, 136.910315`

API結果:

- `Address`: 愛知県 / 名古屋市中区 / 金山 / ５丁目 / ８
- 上位候補: DCM名古屋白金店, 東雲橋西交差点, 東雲橋東交差点, 向田橋西交差点
- `Category=地点名` の交差点が多数

考察:

1位は大型施設だが、2位に正解交差点が出る。郊外/準郊外では交差点優先の方が運転手に伝わる。

### 向田橋西

保存ログ:

- `data/location/placeinfo/20260703_050111_mukaidabashi_west.json`

座標: `35.148124, 136.909713`

API結果:

- 上位候補: 向田橋西交差点, 向田橋東交差点, 東雲橋西交差点, 東雲橋東交差点

考察:

郊外ルールが素直に効く。`Category=地点名` かつ `交差点` を最優先してよい。

### 錦内部コンビニ基準点

保存ログ:

- `data/location/placeinfo/20260703_050142_lawson_nishiki_fukuromachi.json`
- `data/location/placeinfo/20260703_050142_famima_nishiki_shichikencho.json`
- `data/location/placeinfo/20260703_050143_daily_nishiki_isemachi.json`

結果:

- ローソン錦袋町通店は1位、ただし `Roadname=null`
- ファミリーマート錦三七間町通店は1位、交差点候補に錦通七間町/錦通本町/広小路七間町
- デイリーヤマザキ錦伊勢町店は1位、交差点候補に錦通伊勢町/錦通大津

考察:

コンビニは Yahoo データ上では強い。ただし主ラベルにすると `ローソン前繁忙` のように伝達力が落ちる。錦内部では `袋町通（ローソン錦袋町通店前）`、`伊勢町通（デイリーヤマザキ錦伊勢町店付近）` のように補助情報として使うのが良い。

## 都心部と郊外の比較

結論:

- 郊外: `交差点 > 大型施設 > 店舗`
- 都心: `通り名 > 交差点 > 大型ランドマーク > コンビニ`

この仮説は実測ログと合う。

郊外/準郊外では、Yahoo が `Category=地点名` の交差点を比較的素直に返す。特に向田橋西は交差点が1位。東雲橋西は DCM が1位だが、交差点群がすぐ下に並ぶため、交差点優先ルールで正解にできる。

都心では、地下街、ビル内店舗、チェーン飲食、専門店が上位に来る。錦通大津で `すき家サカエチカ店` が1位になるのは、タクシー目線では悪い候補。都心は Yahoo の `Score` をそのまま信じず、通り名と定番ランドマークを強制的に昇格させる必要がある。

## 名古屋都心部の通り文化

名古屋中心部、とくに錦内部では駅名より通り名が強い。通知の主語は `栄駅付近` より `錦通大津`, `袋町通`, `七間町通`, `伊勢町通` の方が現場で理解されやすい。

優先したい通り:

- 七間町通
- 袋町通
- 伊勢町通
- 伝馬町通
- 住吉町通
- 呉服町通
- 木挽町通（通称: カゴメ）
- 錦通
- 広小路通
- 桜通
- 若宮大通

ただし実測では `Roadname` が null になるケースが多い。したがって、錦3丁目は以下のような手動定義を持つべき。

```yaml
nishiki_street_zones:
  - name: 袋町通
    aliases: [袋町]
    priority: 100
    polygon: ...
  - name: 七間町通
    aliases: [七間町]
    priority: 100
    polygon: ...
  - name: 伊勢町通
    aliases: [伊勢町]
    priority: 100
    polygon: ...
```

最初から厳密なポリゴンを作らなくてもよい。Phase4 では緯度経度の矩形または線分からの簡易距離で十分。

## 錦内部ランドマーク優先順位

Sランク:

- 袋町通
- 七間町通
- 住吉町通
- 木挽町通（カゴメ）
- 池田公園
- SUNSHINE SAKAE / サンシャイン栄
- ドン・キホーテ栄本店
- 名古屋銀行本店

Aランク:

- ローソン錦袋町通店
- ファミリーマート錦三七間町通店
- デイリーヤマザキ錦伊勢町店
- ローソン錦七間町通店

コンビニは補助情報とする。例:

- `錦3丁目 袋町通（ローソン錦袋町通店前）繁忙`
- `錦3丁目 伊勢町通（デイリーヤマザキ錦伊勢町店付近）繁忙`

## デイリー問題

錦にはデイリーヤマザキが複数ある。略称 `デイリー前` は禁止。

Yahoo 実測でも以下のように正式店舗名が出る。

- デイリーヤマザキ錦伊勢町店
- デイリーヤマザキ錦3丁目店
- デイリーヤマザキ名古屋女子大小路店

ルール:

- `デイリー` だけに短縮しない
- 表示するなら `デイリーヤマザキ錦伊勢町店` のように正式名
- 主ラベルではなく補助ラベル
- 複数候補が近い場合は町名/通り名を優先し、コンビニは括弧内へ落とす

## 地下街・空中店舗問題

除外または大幅降格したい候補:

- サカエチカ
- エスカ
- ユニモール
- 地下街名を含む店舗
- ビル内テナント
- 高層階店舗
- `○階`, `B1`, `地下`, `フロア`, `店内`, `館内`
- 石井スポーツ名古屋店のような大型ビル内店舗
- 飲食店チェーンの地下街店舗

除外ロジック案:

```python
UNDERGROUND_WORDS = (
    "サカエチカ", "エスカ", "ユニモール", "地下", "地下街", "B1", "Ｂ１",
    "駅構内", "改札内", "フロア", "階", "館内"
)

AIR_TENANT_WORDS = (
    "ビル", "店内", "センター内", "モール内", "タワーズ内"
)

def place_penalty(candidate):
    text = f"{candidate.name} {candidate.combined} {candidate.category}"
    penalty = 0
    if any(word in text for word in UNDERGROUND_WORDS):
        penalty += 80
    if any(word in text for word in AIR_TENANT_WORDS):
        penalty += 30
    if candidate.category in {"その他のファミリーレストラン", "大型専門店（スポーツ・アウトドア）"}:
        penalty += 20
    return penalty
```

完全除外ではなく降格が安全。地下街店舗でも、他に候補がないときのデバッグ材料にはなる。

## Yahooロコ由来仮説

実測上、Yahoo は以下に強い。

- 交差点
- ホテル
- コンビニ本部登録
- 行政/公共施設
- 大企業/銀行
- ドンキ、アパ、サンシャインのような大型/チェーン施設
- 地下街や商業施設内の登録店舗

弱い、またはタクシー目線とズレやすいもの:

- 業界通称
- 繁華街のビル名/空中店舗
- 小規模店舗
- 新店舗
- 公園や通称スポット
- 錦内部の細かい通り名

池田公園が Yahoo 候補に出なかったこと、錦通大津で地下街店舗が1位になったことは、この仮説を支持する。Yahoo データは「施設検索」としては強いが、「タクシー繁忙地点ラベル」としては補正が必須。

## 推奨アルゴリズム

### 1. 正規化

```python
def normalize_address(address_parts):
    # ["愛知県", "名古屋市中区", "錦", "３丁目", "１７"] -> "錦3丁目"
    town = address_parts[2] if len(address_parts) >= 3 else ""
    chome = address_parts[3] if len(address_parts) >= 4 else ""
    chome = chome.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    return f"{town}{chome}" if town and "丁目" in chome else town
```

### 2. エリア判定

```python
def classify_zone(lat, lon, address_label):
    if address_label.startswith("錦3丁目"):
        return "nishiki_core"
    if address_label.startswith(("栄4丁目", "栄5丁目")):
        return "sakae_joshidai"
    if address_label.startswith(("金山5丁目", "平和2丁目")):
        return "suburban_intersection"
    return "default"
```

### 3. 候補分類

```python
def candidate_kind(candidate):
    name = candidate["name"]
    category = candidate.get("category", "")
    if category == "地点名" and "交差点" in name:
        return "intersection"
    if category in {"ローソン", "ファミリーマート", "デイリーヤマザキ", "セブン-イレブン"}:
        return "convenience"
    if "ホテル" in category:
        return "hotel"
    if "ショッピングセンター" in category or "複合商業施設" in category:
        return "large_landmark"
    return "store"
```

### 4. 秘伝のタレDBを先に見る

最優先は手動補正DB。座標半径は都心 40-70m、郊外 80-150m から開始。

```yaml
overrides:
  - id: sakae_ikeda_park
    lat: 35.166337
    lon: 136.912610
    radius_m: 80
    label: 栄4丁目 池田公園付近
    priority: 1000
  - id: nishiki_odori_otsu_sunshine
    lat: 35.169973
    lon: 136.906720
    radius_m: 60
    label: 錦通大津（サンシャイン栄付近）
    priority: 1000
```

### 5. 地域別スコアリング

```python
def rank_candidate(candidate, zone):
    score = float(candidate.get("score") or 0)
    kind = candidate_kind(candidate)

    if zone == "suburban_intersection":
        bonus = {
            "intersection": 120,
            "large_landmark": 60,
            "hotel": 25,
            "convenience": 10,
            "store": 0,
        }[kind]
    elif zone in {"nishiki_core", "sakae_joshidai"}:
        bonus = {
            "intersection": 70,
            "large_landmark": 65,
            "hotel": 35,
            "convenience": 25,
            "store": 0,
        }[kind]
    else:
        bonus = {
            "intersection": 80,
            "large_landmark": 60,
            "hotel": 40,
            "convenience": 30,
            "store": 10,
        }[kind]

    return score + bonus - place_penalty(candidate)
```

### 6. ラベル組み立て

都心:

1. 秘伝のタレDBに当たればそれを採用
2. 錦内部の通りゾーンに当たれば `錦3丁目 <通り名>`
3. 近くに S/A ランク補助があれば括弧で追加
4. 交差点が強ければ `錦通大津` のように `交差点` を落として表示
5. コンビニのみの場合は正式名称で括弧補助

郊外:

1. `Category=地点名` + `交差点` を最優先
2. 交差点名が取れなければ大型施設
3. それもなければ町名 + 店舗/施設

## 実装ロードマップ

### Phase1: Yahoo PlaceInfoそのまま

完了済みに近い。現状は候補名のみ投稿できている。

追加すること:

- `Category`, `Score`, `Uid`, `Where`, `Roadname`, `Address`, `Area` を保存/表示
- Discord テスト出力に raw path を残す

### Phase2: 地下街・空中店舗除外

錦通大津/名駅で効果が大きい。

- サカエチカ、エスカ、ユニモールを降格
- `階`, `地下`, `店内`, `ビル内` を含む候補を降格
- 飲食店・専門店は、交差点/大型ランドマークがある場合は主候補から外す

### Phase3: 郊外は交差点優先

東雲橋西/向田橋西で即効性がある。

- `Category=地点名` かつ `交差点` を最優先
- `...交差点付近` で出力
- 近接する西/東交差点の取り違えを防ぐため、候補順位とスコア差をログに残す

### Phase4: 都心は通り名優先

錦内部の本命。

- `錦3丁目` エリアを特別扱い
- 袋町通、七間町通、伊勢町通、伝馬町通、住吉町通、呉服町通、木挽町通を手動ゾーン化
- `Roadname` が取れた場合は Yahoo の値も使う
- `錦通大津`, `錦通伊勢町`, `広小路七間町` は交差点名から生成

### Phase5: 秘伝のタレDB導入

最も実用価値が高い。

推奨ファイル:

- `data/location/place_label_overrides.yml`
- 将来的に Google Sheets 同期も可

例:

```yaml
version: 1
spots:
  - id: sakae4_ikeda_park
    lat: 35.166337
    lon: 136.912610
    radius_m: 80
    label: 栄4丁目 池田公園付近
    source: user_corrected
    confidence: confirmed
  - id: nishiki_odori_otsu_sunshine
    lat: 35.169973
    lon: 136.906720
    radius_m: 60
    label: 錦通大津（サンシャイン栄付近）
    source: user_corrected
    confidence: confirmed
```

### Phase6: Gemma課長による自動学習

Discord の正解リプライを使って、候補DBを育てる。

流れ:

```text
GPS
↓
Yahoo候補 + 自動生成ラベル
↓
Discord投稿
↓
ユーザーが返信で正解ラベル
↓
Gemma課長/バッチ処理が補正案を作成
↓
人間確認
↓
秘伝のタレDB更新
```

自動更新は危険なので、最初は `pending_overrides.yml` に候補を書くだけにする。

```yaml
pending:
  - lat: 35.166337
    lon: 136.912610
    generated_label: 東栄通（アパホテル名古屋栄付近）
    corrected_label: 栄4丁目 池田公園付近
    discord_message_id: "..."
    status: pending_review
```

## サンプルコード案

```python
def build_taxi_place_label(placeinfo):
    address_label = normalize_address(placeinfo["address_parts"])
    zone = classify_zone(placeinfo["lat"], placeinfo["lon"], address_label)

    override = find_override(placeinfo["lat"], placeinfo["lon"])
    if override:
        return f"{override.label}繁忙"

    if zone == "nishiki_core":
        street = find_nishiki_street(placeinfo["lat"], placeinfo["lon"])
        landmark = find_ranked_landmark(placeinfo["candidates"], zone)
        if street and landmark and landmark["kind"] == "convenience":
            return f"{address_label} {street}（{landmark['name']}前）繁忙"
        if street:
            return f"{address_label} {street}繁忙"

    candidates = sorted(
        placeinfo["candidates"],
        key=lambda item: rank_candidate(item, zone),
        reverse=True,
    )
    best = candidates[0] if candidates else None
    if not best:
        return f"{address_label}繁忙"

    if candidate_kind(best) == "intersection":
        name = best["name"].replace("交差点", "")
        return f"{name}交差点付近繁忙"

    if candidate_kind(best) == "large_landmark":
        return f"{address_label}（{normalize_landmark(best['name'])}付近）繁忙"

    return f"{address_label} {best['name']}付近繁忙"
```

## 実装時の注意点

- Yahoo の `Score` はタクシー目線の正解度ではない
- `Roadname` は出たら強いが、錦内部では null が多い
- コンビニ名は正式名称を保持する
- `デイリー前` のような略称は禁止
- 地下街/駅構内/ビル内店舗は主ラベルにしない
- 秘伝のタレDBは必ず人間がレビューできる形にする
- 保存するのは座標、候補、補正ラベル、メッセージID程度に抑える
- 個人名、乗務員、売上、乗車実績は保存しない

## 推奨する次の実装順

1. `extract_candidates()` を拡張して raw の判断材料を失わないようにする
2. `format_placeinfo_result()` に `Roadname`, `Address`, `Category`, `Score` をデバッグ表示する
3. `build_taxi_place_label()` を新規作成し、Discord投稿の1行目に採用する
4. Phase2 の地下街/空中店舗降格を入れる
5. Phase3 の交差点優先を入れる
6. `place_label_overrides.yml` を作り、池田公園と錦通大津を初期登録する
7. 錦内部の通りゾーンを追加する
8. Discord返信から `pending_overrides.yml` を作る学習補助を追加する

## 現時点の結論

Yahoo PlaceInfo は「候補収集エンジン」としては十分使える。ただし、そのまま出すと都心では地下街・店舗・ビル内テナントに引っ張られる。繁忙ボタンの最終ラベルは、Yahoo 候補、地域別ルール、錦内部の通りDB、秘伝のタレDBを合成して作るのが正解。

特に錦は通り文化を最優先する。Yahoo の1位候補より、`錦3丁目 + 通り名 + 補助ランドマーク` の方が、タクシー運転手には速く伝わる。
