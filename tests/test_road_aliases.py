from pathlib import Path

from tools.location.road_aliases import infer_road_alias_from_result, load_road_aliases, match_road_aliases, normalize_intersection_name


def test_normalize_intersection_name_accepts_suffix_variants():
    assert normalize_intersection_name("桜通大津交差点") == normalize_intersection_name("桜通大津")
    assert normalize_intersection_name("錦通 大津 交差点") == normalize_intersection_name("錦通大津")


def test_normalize_intersection_name_accepts_mitsukura_variants():
    canonical = normalize_intersection_name("三蔵通大津交差点")

    assert normalize_intersection_name("三ッ蔵通大津交差点") == canonical
    assert normalize_intersection_name("三ツ蔵通大津交差点") == canonical


def test_sakuradori_known_intersection_matches_sakuradori():
    matches = match_road_aliases("桜通大津交差点")

    assert "桜通" in [match["name"] for match in matches]


def test_nishikidori_known_intersection_matches_nishikidori():
    matches = match_road_aliases("錦通本町")

    assert "錦通" in [match["name"] for match in matches]


def test_hirokojidori_known_intersection_matches_hirokojidori():
    matches = match_road_aliases("広小路伏見交差点")

    assert "広小路通" in [match["name"] for match in matches]


def test_added_major_roads_match_known_intersections():
    cases = [
        ("名古屋駅交差点", "名駅通"),
        ("柳橋交差点", "江川線"),
        ("日銀前交差点", "伏見通"),
        ("若宮大通本町交差点", "本町通"),
        ("錦通大津交差点", "大津通"),
        ("錦三丁目交差点", "大津通"),
        ("錦通久屋交差点", "久屋大通"),
        ("高岳交差点", "空港線"),
        ("大津橋交差点", "外堀通"),
        ("若宮大通久屋交差点", "若宮大通"),
        ("西大須交差点", "大須通"),
        ("東別院交差点", "山王通"),
        ("三蔵通本町交差点", "三蔵通"),
        ("三蔵通大津交差点", "三蔵通"),
        ("三ッ蔵通大津交差点", "三蔵通"),
        ("三ッ蔵通大津交差点", "大津通"),
        ("三蔵交差点", "三蔵通"),
        ("三ッ蔵通久屋西", "三蔵通"),
        ("三蔵通久屋西", "三蔵通"),
        ("錦通伊勢町交差点", "錦通"),
        ("天王崎橋東交差点", "三蔵通"),
        ("天王崎橋交差点", "三蔵通"),
        ("伏見魚ノ棚交差点", "伏見通"),
    ]

    for intersection, expected in cases:
        assert expected in [match["name"] for match in match_road_aliases(intersection)]


def test_mitsukuradori_records_osm_geometry_source():
    road = next(item for item in load_road_aliases() if item["id"] == "mitsukuradori")

    assert road["source_url"] == "https://www.openstreetmap.org/way/31512981"
    assert "31512981" in road["geometry"]
    assert "1448535861" in road["geometry"]
    assert "OSM Overpass" in road["note"]


def test_infer_combines_east_west_and_north_south_roads():
    cases = [
        ("錦通大津交差点", "錦通 × 大津通", "錦通", "大津通"),
        ("三ッ蔵通大津交差点", "三蔵通 × 大津通", "三蔵通", "大津通"),
        ("若宮大通久屋交差点", "若宮大通 × 久屋大通", "若宮大通", "久屋大通"),
        ("高岳交差点", "桜通 × 空港線", "桜通", "空港線"),
    ]

    for intersection, expected, east_west, north_south in cases:
        inferred = infer_road_alias_from_result({"roadname": "", "candidates": [{"name": intersection, "category": "地点名"}]})
        assert inferred["adopted_roadname"] == expected
        assert inferred["east_west_road"]["name"] == east_west
        assert inferred["north_south_road"]["name"] == north_south
        assert inferred["reason"] == "同一Yahoo交差点から東西道路と南北道路を1本ずつ採用"


def test_infer_keeps_single_direction_road_name():
    inferred = infer_road_alias_from_result({"roadname": "", "candidates": [{"name": "錦三丁目交差点", "category": "地点名"}]})

    assert inferred["adopted_roadname"] == "大津通"
    assert inferred["east_west_road"] == {}
    assert inferred["north_south_road"]["name"] == "大津通"


def test_unknown_intersection_returns_empty():
    assert match_road_aliases("未登録交差点") == []


def test_infer_keeps_multiple_road_candidates_without_adopting(tmp_path: Path):
    alias_path = tmp_path / "road_aliases.yml"
    alias_path.write_text(
        """version: 1
roads:
  - id: road_a
    name: A通
    direction: east_west
    aliases: [A通]
    source_url: https://example.com/a
    start: 共有交差点
    end: A終点
    road_numbers: []
    intersections: [共有交差点]
    geometry:
    note: test

  - id: road_b
    name: B通
    direction: east_west
    aliases: [B通]
    source_url: https://example.com/b
    start: 共有交差点
    end: B終点
    road_numbers: []
    intersections: [共有交差点]
    geometry:
    note: test
""",
        encoding="utf-8",
    )
    result = {
        "roadname": "県道1号線",
        "candidates": [{"name": "共有交差点", "category": "地点名"}],
    }

    inferred = infer_road_alias_from_result(result, path=alias_path)

    assert inferred["adopted_roadname"] == ""
    assert [candidate["name"] for candidate in inferred["road_alias_candidates"]] == ["A通", "B通"]
    assert inferred["reason"] == "同一Yahoo交差点内で同方向の複数道路候補があり未確定"


def test_infer_adopts_yahoo_roadname_when_multiple_candidates_match(tmp_path: Path):
    alias_path = tmp_path / "road_aliases.yml"
    alias_path.write_text(
        """version: 1
roads:
  - id: hirokoji
    name: 広小路通
    direction: east_west
    aliases: [広小路通]
    source_url: https://example.com/hirokoji
    start: 共有交差点
    end: 広小路終点
    road_numbers: []
    intersections: [共有交差点]
    geometry:
    note: test

  - id: nishiki
    name: 錦通
    direction: east_west
    aliases: [錦通]
    source_url: https://example.com/nishiki
    start: 共有交差点
    end: 錦終点
    road_numbers: []
    intersections: [共有交差点]
    geometry:
    note: test
""",
        encoding="utf-8",
    )
    result = {
        "roadname": "広小路通",
        "candidates": [{"name": "共有交差点", "category": "地点名"}],
    }

    inferred = infer_road_alias_from_result(result, path=alias_path)

    assert inferred["adopted_roadname"] == "広小路通"
    assert inferred["reason"] == "同一Yahoo交差点から片方向の道路候補を採用"
    assert inferred["direction_reasons"]["east_west"] == "同方向の複数道路候補からYahoo roadname一致を採用"


def test_infer_uses_yahoo_roadname_fallback_when_alias_is_missing():
    result = {
        "roadname": "伏見通",
        "candidates": [{"name": "丸の内オフランプ交差点", "category": "地点名"}],
    }

    inferred = infer_road_alias_from_result(result)

    assert inferred["adopted_roadname"] == "伏見通"
    assert inferred["road_alias_candidates"] == []
    assert inferred["reason"] == "表示用交差点がroad_aliases.ymlに未登録のためYahoo roadnameを採用"


def test_infer_canonicalizes_yahoo_roadname_fallback():
    result = {
        "roadname": "伊勢町通り",
        "candidates": [{"name": "未登録交差点", "category": "地点名"}],
    }

    inferred = infer_road_alias_from_result(result)

    assert inferred["adopted_roadname"] == "伊勢町通"


def test_infer_does_not_mix_road_aliases_from_different_intersections(tmp_path: Path):
    alias_path = tmp_path / "road_aliases.yml"
    alias_path.write_text(
        """version: 1
roads:
  - id: east_road
    name: 東西通
    direction: east_west
    aliases: [東西通]
    source_url: https://example.com/east
    start: A交差点
    end: 東西終点
    road_numbers: []
    intersections: [A交差点]
    geometry:
    note: test

  - id: north_road
    name: 南北通
    direction: north_south
    aliases: [南北通]
    source_url: https://example.com/north
    start: B交差点
    end: 南北終点
    road_numbers: []
    intersections: [B交差点]
    geometry:
    note: test
""",
        encoding="utf-8",
    )
    result = {
        "roadname": "",
        "candidates": [
            {"name": "A交差点", "category": "地点名"},
            {"name": "B交差点", "category": "地点名"},
        ],
    }

    inferred = infer_road_alias_from_result(result, path=alias_path)

    assert inferred["adopted_roadname"] == "東西通"
    assert inferred["selected_yahoo_intersection"] == "A交差点"
    assert [candidate["name"] for candidate in inferred["road_alias_candidates"]] == ["東西通"]
    assert [candidate["name"] for candidate in inferred["all_road_alias_candidates"]] == ["東西通", "南北通"]


def test_infer_uses_only_adopted_intersection_for_display_road_alias():
    result = {
        "roadname": "",
        "candidates": [
            {"name": "丸の内オフランプ交差点", "category": "地点名"},
            {"name": "新御園橋交差点", "category": "地点名"},
            {"name": "伏見魚ノ棚交差点", "category": "地点名"},
        ],
    }

    inferred = infer_road_alias_from_result(result, adopted_intersection="丸の内オフランプ交差点")

    assert inferred["adopted_roadname"] == ""
    assert inferred["selected_yahoo_intersection"] == "丸の内オフランプ交差点"
    assert inferred["road_alias_candidates"] == []
    assert [candidate["name"] for candidate in inferred["all_road_alias_candidates"]] == ["外堀通", "伏見通"]
    assert inferred["reason"] == "表示用交差点がroad_aliases.ymlに未登録"


def test_infer_adopts_road_alias_from_adopted_intersection_itself():
    result = {
        "roadname": "",
        "candidates": [
            {"name": "丸の内オフランプ交差点", "category": "地点名"},
            {"name": "伏見魚ノ棚交差点", "category": "地点名"},
        ],
    }

    inferred = infer_road_alias_from_result(result, adopted_intersection="伏見魚ノ棚交差点")

    assert inferred["adopted_roadname"] == "伏見通"
    assert inferred["selected_yahoo_intersection"] == "伏見魚ノ棚交差点"
    assert [candidate["name"] for candidate in inferred["road_alias_candidates"]] == ["伏見通"]


def test_infer_combines_roads_only_when_adopted_intersection_has_both():
    result = {
        "roadname": "",
        "candidates": [
            {"name": "丸の内オフランプ交差点", "category": "地点名"},
            {"name": "錦通大津交差点", "category": "地点名"},
        ],
    }

    inferred = infer_road_alias_from_result(result, adopted_intersection="錦通大津交差点")

    assert inferred["adopted_roadname"] == "錦通 × 大津通"
    assert inferred["east_west_road"]["name"] == "錦通"
    assert inferred["north_south_road"]["name"] == "大津通"


def test_infer_uses_yahoo_roadname_fallback_for_adopted_intersection_when_alias_is_missing():
    result = {
        "roadname": "伏見通",
        "candidates": [
            {"name": "丸の内オフランプ交差点", "category": "地点名"},
            {"name": "新御園橋交差点", "category": "地点名"},
        ],
    }

    inferred = infer_road_alias_from_result(result, adopted_intersection="丸の内オフランプ交差点")

    assert inferred["adopted_roadname"] == "伏見通"
    assert inferred["selected_yahoo_intersection"] == "丸の内オフランプ交差点"
    assert inferred["road_alias_candidates"] == []
    assert inferred["reason"] == "表示用交差点がroad_aliases.ymlに未登録のためYahoo roadnameを採用"


def test_infer_known_added_intersections():
    cases = [
        ("錦通伊勢町交差点", "錦通"),
        ("天王崎橋東交差点", "三蔵通"),
        ("天王崎橋交差点", "三蔵通"),
        ("伏見魚ノ棚交差点", "伏見通"),
    ]

    for intersection, expected in cases:
        inferred = infer_road_alias_from_result({"roadname": "", "candidates": [{"name": intersection, "category": "地点名"}]})
        assert inferred["adopted_roadname"] == expected
