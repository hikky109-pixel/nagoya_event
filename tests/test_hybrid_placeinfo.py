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


def test_hybrid_uses_osm_road_with_yahoo_landmark():
    osm = {
        "lat": 35.165145,
        "lon": 136.907102,
        "address": ["日本", "名古屋市中区", "栄3丁目"],
        "short_address": "中区栄3丁目",
        "roadname": "大津通",
        "candidates": [{"name": "大津通", "kind": "road", "score": 80.0}],
        "taxi_label": {"label": "大津通付近"},
    }
    yahoo = {
        "lat": 35.165145,
        "lon": 136.907102,
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
    assert result["taxi_label"]["label"] == "大津通（松坂屋名古屋店付近）"


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

    assert result["taxi_label"]["label"] == "パルコ付近"


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

    assert result["taxi_label"]["label"] == "白川通（松坂屋名古屋店付近）"
