from tools.location.get_hybrid_placeinfo import build_hybrid_result


def test_hybrid_uses_yahoo_intersection_when_osm_has_no_road():
    osm = {
        "lat": 35.158953,
        "lon": 136.856430,
        "address": ["日本", "名古屋市中村区", "乾出町1丁目"],
        "short_address": "中村区乾出町1丁目",
        "roadname": "",
        "candidates": [{"name": "乾出町1丁目", "kind": "store", "score": 90.0}],
        "taxi_label": {"label": "乾出町1丁目付近"},
    }
    yahoo = {
        "lat": 35.158953,
        "lon": 136.856430,
        "address": ["愛知県", "名古屋市中村区", "沖田町"],
        "short_address": "中村区沖田町",
        "roadname": "",
        "candidates": [
            {"name": "ケーズデンキ岩塚店", "category": "家電量販店", "score": 80.0},
            {"name": "畑江通八交差点", "category": "地点名", "score": 50.0},
        ],
        "taxi_label": {"label": "畑江通八交差点付近"},
    }

    result = build_hybrid_result(osm, yahoo)

    assert result["comparison"]["osm_label"] == "乾出町1丁目付近"
    assert result["comparison"]["yahoo_label"] == "畑江通八交差点付近"
    assert result["short_address"] == "中村区沖田町"
    assert result["taxi_label"]["label"] == "畑江通八交差点付近"
    assert result["display_lines"]["text"] == "📍 中村区沖田町\n🚥 畑江通八交差点\n座標: 35.158953, 136.856430"


def test_hybrid_display_ignores_osm_candidates():
    osm = {
        "lat": 35.0,
        "lon": 136.0,
        "address": ["日本", "名古屋市中区", "栄3丁目"],
        "short_address": "中区栄3丁目",
        "roadname": "OSM通り",
        "candidates": [
            {"name": "OSMだけの大型施設", "kind": "large_landmark", "score": 100.0},
            {"name": "OSM通り", "kind": "road", "score": 100.0},
        ],
        "taxi_label": {"label": "OSM通り（OSMだけの大型施設付近）"},
    }
    yahoo = {
        "lat": 35.0,
        "lon": 136.0,
        "address": ["愛知県", "名古屋市中区", "栄", "３丁目"],
        "short_address": "中区栄3丁目",
        "roadname": "",
        "candidates": [
            {"name": "三蔵通久屋西", "category": "地点名", "score": 50.0},
            {"name": "ラシック", "category": "ショッピングセンター・モール、複合商業施設", "score": 80.0},
        ],
        "taxi_label": {"label": "三蔵通久屋西付近"},
    }

    result = build_hybrid_result(osm, yahoo)

    assert result["display_lines"]["text"] == "📍 中区栄3丁目\n🚥 三蔵通久屋西\n座標: 35.000000, 136.000000"
    assert "OSM" not in result["display_lines"]["text"]


def test_hybrid_uses_osm_road_with_yahoo_landmark():
    osm = {
        "lat": 35.0,
        "lon": 136.0,
        "address": ["日本", "名古屋市中区", "栄3丁目"],
        "short_address": "中区栄3丁目",
        "roadname": "大津通",
        "candidates": [{"name": "大津通", "kind": "road", "score": 80.0}],
        "taxi_label": {"label": "大津通付近"},
    }
    yahoo = {
        "lat": 35.0,
        "lon": 136.0,
        "address": ["愛知県", "名古屋市中区", "栄", "３丁目"],
        "short_address": "中区栄3丁目",
        "roadname": "",
        "candidates": [
            {"name": "松坂屋名古屋店", "category": "百貨店、デパート", "score": 95.0},
            {"name": "ローソン栄三丁目店", "category": "ローソン", "score": 20.0},
        ],
        "taxi_label": {"label": "栄3丁目 松坂屋名古屋店付近"},
    }

    result = build_hybrid_result(osm, yahoo)

    assert result["comparison"]["osm_label"] == "大津通付近"
    assert result["comparison"]["yahoo_label"] == "栄3丁目 松坂屋名古屋店付近"
    assert result["taxi_label"]["label"] == "松坂屋名古屋店付近"


def test_hybrid_does_not_promote_tenant_containing_landmark_name():
    osm = {
        "lat": 35.1638,
        "lon": 136.9077,
        "address": ["日本", "名古屋市中区", "栄3丁目"],
        "short_address": "中区栄3丁目",
        "roadname": "",
        "candidates": [{"name": "パルコ", "kind": "large_landmark", "score": 100.0}],
        "taxi_label": {"label": "栄3丁目（パルコ付近）"},
    }
    yahoo = {
        "lat": 35.1638,
        "lon": 136.9077,
        "address": ["愛知県", "名古屋市中区", "栄", "３丁目"],
        "short_address": "中区栄3丁目",
        "roadname": "",
        "candidates": [
            {"name": "サブウェイ名古屋パルコ店", "category": "サブウェイ", "score": 95.0},
            {"name": "名古屋パルコ西館", "category": "パルコ", "score": 90.0},
        ],
        "taxi_label": {"label": "栄3丁目 サブウェイ名古屋パルコ店付近"},
    }

    result = build_hybrid_result(osm, yahoo)

    assert result["taxi_label"]["label"] == "名古屋パルコ西館付近"
    assert "サブウェイ" not in result["taxi_label"]["label"]


def test_hybrid_prefers_named_landmark_over_building_name():
    osm = {
        "lat": 35.1662,
        "lon": 136.9081,
        "address": ["日本", "名古屋市中区", "栄3丁目"],
        "short_address": "中区栄3丁目",
        "roadname": "白川通",
        "candidates": [{"name": "エンゼルビル松坂屋本店北館", "kind": "large_landmark", "score": 100.0}],
        "taxi_label": {"label": "白川通（エンゼルビル松坂屋本店北館付近）"},
    }
    yahoo = {
        "lat": 35.1662,
        "lon": 136.9081,
        "address": ["愛知県", "名古屋市中区", "栄", "３丁目"],
        "short_address": "中区栄3丁目",
        "roadname": "",
        "candidates": [{"name": "松坂屋名古屋店", "category": "松坂屋", "score": 80.0}],
        "taxi_label": {"label": "栄3丁目 松坂屋名古屋店付近"},
    }

    result = build_hybrid_result(osm, yahoo)

    assert result["taxi_label"]["label"] == "松坂屋名古屋店付近"


def test_hybrid_yahoo_intersection_beats_osm_road():
    osm = {
        "lat": 35.173,
        "lon": 136.904,
        "address": ["日本", "名古屋市中区", "錦3丁目"],
        "short_address": "中区錦3丁目",
        "roadname": "桜通",
        "candidates": [{"name": "桜通", "kind": "road", "score": 100.0}],
        "taxi_label": {"label": "桜通付近"},
    }
    yahoo = {
        "lat": 35.173,
        "lon": 136.904,
        "address": ["愛知県", "名古屋市中区", "錦", "３丁目"],
        "short_address": "中区錦3丁目",
        "roadname": "",
        "candidates": [
            {"name": "桜通呉服交差点", "category": "地点名", "score": 50.0},
            {"name": "ローソン錦三丁目店", "category": "ローソン", "score": 90.0},
        ],
        "taxi_label": {"label": "ローソン錦三丁目店付近"},
    }

    result = build_hybrid_result(osm, yahoo)

    assert result["taxi_label"]["label"] == "桜通呉服交差点付近"
    assert result["taxi_label"]["source"] == "yahoo_intersection"


def test_hybrid_yahoo_intersection_beats_landmark_and_road():
    osm = {
        "lat": 35.158953,
        "lon": 136.856430,
        "address": ["日本", "名古屋市中村区", "乾出町1丁目"],
        "short_address": "中村区乾出町1丁目",
        "roadname": "畑江通",
        "candidates": [{"name": "畑江通", "kind": "road", "score": 100.0}],
        "taxi_label": {"label": "畑江通付近"},
    }
    yahoo = {
        "lat": 35.158953,
        "lon": 136.856430,
        "address": ["愛知県", "名古屋市中村区", "沖田町"],
        "short_address": "中村区沖田町",
        "roadname": "",
        "candidates": [
            {"name": "ケーズデンキ岩塚店", "category": "家電量販店", "score": 95.0},
            {"name": "畑江通八交差点", "category": "地点名", "score": 40.0},
        ],
        "taxi_label": {"label": "ケーズデンキ岩塚店付近"},
    }

    result = build_hybrid_result(osm, yahoo)

    assert result["taxi_label"]["label"] == "畑江通八交差点付近"


def test_hybrid_osm_taikodori_does_not_override_yahoo_intersection():
    osm = {
        "lat": 35.0,
        "lon": 136.0,
        "address": ["日本", "名古屋市中村区", "太閤1丁目"],
        "short_address": "中村区太閤1丁目",
        "roadname": "太閤通",
        "candidates": [{"name": "太閤通", "kind": "road", "score": 100.0}],
        "taxi_label": {"label": "太閤通付近"},
    }
    yahoo = {
        "lat": 35.0,
        "lon": 136.0,
        "address": ["愛知県", "名古屋市中村区", "太閤", "１丁目"],
        "short_address": "中村区太閤1丁目",
        "roadname": "",
        "candidates": [{"name": "笹島交差点", "category": "地点名", "score": 50.0}],
        "taxi_label": {"label": "笹島交差点付近"},
    }

    result = build_hybrid_result(osm, yahoo)

    assert result["taxi_label"]["label"] == "笹島交差点付近"
    assert result["road_alias"]["adopted_roadname"] == "広小路通 × 名駅通"
    assert [candidate["name"] for candidate in result["road_alias"]["road_alias_candidates"]] == ["広小路通", "名駅通"]
    assert result["display_lines"]["text"] == "📍 中村区太閤1丁目\n🛣️ 広小路通 × 名駅通\n🚥 笹島交差点\n座標: 35.000000, 136.000000"


def test_hybrid_road_alias_uses_display_intersection_only():
    osm = {
        "lat": 35.176371,
        "lon": 136.896264,
        "candidates": [],
        "taxi_label": {},
    }
    yahoo = {
        "lat": 35.176371,
        "lon": 136.896264,
        "address": ["愛知県", "名古屋市中区", "丸の内", "１丁目"],
        "short_address": "中区丸の内1丁目",
        "roadname": "",
        "candidates": [
            {"name": "丸の内オフランプ交差点", "category": "地点名", "score": 90.0},
            {"name": "新御園橋交差点", "category": "地点名", "score": 70.0},
            {"name": "伏見魚ノ棚交差点", "category": "地点名", "score": 60.0},
        ],
        "taxi_label": {"label": "丸の内オフランプ交差点付近"},
    }

    result = build_hybrid_result(osm, yahoo)

    assert result["display_intersection"] == "丸の内オフランプ交差点"
    assert result["road_alias"]["adopted_roadname"] == ""
    assert result["road_alias"]["selected_yahoo_intersection"] == "丸の内オフランプ交差点"
    assert [candidate["name"] for candidate in result["road_alias"]["all_road_alias_candidates"]] == ["外堀通", "伏見通"]
    assert result["display_lines"]["text"] == "📍 中区丸の内1丁目\n🚥 丸の内オフランプ交差点\n座標: 35.176371, 136.896264"


def test_hybrid_shinkansen_tp_live_gps_offset_shows_taxi_ops_line():
    osm = {
        "lat": 35.170216,
        "lon": 136.880259,
        "candidates": [],
        "taxi_label": {},
    }
    yahoo = {
        "lat": 35.170216,
        "lon": 136.880259,
        "address": ["愛知県", "名古屋市中村区", "椿町"],
        "short_address": "中村区椿町",
        "roadname": "",
        "candidates": [{"name": "椿町北交差点", "category": "地点名", "score": 80.0}],
        "taxi_label": {"label": "椿町北交差点付近"},
    }

    result = build_hybrid_result(osm, yahoo)

    assert result["taxi_label"]["label"] == "新幹線口TP"
    assert result["taxi_label"]["debug"]["override_id"] == "nagoya_station_taikodori_taxi_stand"
    assert result["taxi_label"]["debug"]["radius_m"] == 60
    assert result["display_lines"]["text"] == "📍 中村区椿町\n🚥 椿町北交差点\n🚖 新幹線口TP\n座標: 35.170216, 136.880259"


def test_hybrid_shinkansen_tp_outside_radius_does_not_show_taxi_ops_line():
    osm = {
        "lat": 35.170216,
        "lon": 136.879700,
        "candidates": [],
        "taxi_label": {},
    }
    yahoo = {
        "lat": 35.170216,
        "lon": 136.879700,
        "address": ["愛知県", "名古屋市中村区", "椿町"],
        "short_address": "中村区椿町",
        "roadname": "",
        "candidates": [{"name": "椿町北交差点", "category": "地点名", "score": 80.0}],
        "taxi_label": {"label": "椿町北交差点付近"},
    }

    result = build_hybrid_result(osm, yahoo)

    assert result["taxi_label"]["label"] == "椿町北交差点付近"
    assert "🚖" not in result["display_lines"]["text"]
