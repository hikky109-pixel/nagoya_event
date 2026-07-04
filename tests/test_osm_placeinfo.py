from tools.location.get_osm_placeinfo import build_placeinfo_result


TEST_LAT = 35.0
TEST_LON = 136.0


def test_osm_payload_builds_road_label_with_landmark():
    payload = {
        "place_id": 1,
        "osm_type": "way",
        "osm_id": 123,
        "category": "shop",
        "type": "department_store",
        "display_name": "松坂屋 名古屋店, 大津通, 栄三丁目, 中区, 名古屋市, 愛知県, 日本",
        "namedetails": {"name": "松坂屋 名古屋店"},
        "address": {
            "shop": "松坂屋 名古屋店",
            "road": "大津通",
            "quarter": "栄",
            "city_district": "中区",
            "city": "名古屋市",
            "country": "日本",
        },
    }

    result = build_placeinfo_result(TEST_LAT, TEST_LON, payload, area="test_osm")

    assert result["source"] == "OSMNominatim"
    assert result["short_address"] == "中区栄"
    assert result["roadname"] == "大津通"
    assert result["taxi_label"]["label"] == "大津通（松坂屋 名古屋店付近）"
    assert any(candidate["name"] == "大津通" for candidate in result["candidates"])


def test_osm_address_parts_handle_japanese_ward_and_chome():
    payload = {
        "place_id": 3,
        "osm_type": "way",
        "osm_id": 789,
        "category": "highway",
        "type": "unclassified",
        "display_name": "栄三丁目, 栄, 中区, 名古屋市, 愛知県, 460-0008, 日本",
        "address": {
            "neighbourhood": "栄三丁目",
            "suburb": "中区",
            "city": "名古屋市",
            "country": "日本",
        },
    }

    result = build_placeinfo_result(TEST_LAT, TEST_LON, payload, area="test_osm")

    assert result["short_address"] == "中区栄3丁目"
    assert result["taxi_label"]["label"] == "栄3丁目付近"


def test_osm_payload_keeps_requested_candidate_fields():
    payload = {
        "place_id": 2,
        "osm_type": "node",
        "osm_id": 456,
        "category": "amenity",
        "type": "theatre",
        "display_name": "御園座, 伏見通, 栄一丁目, 中区, 名古屋市, 愛知県, 日本",
        "namedetails": {"name": "御園座"},
        "address": {
            "amenity": "御園座",
            "road": "伏見通",
            "quarter": "栄",
            "city_district": "中区",
            "city": "名古屋市",
            "country": "日本",
        },
    }

    result = build_placeinfo_result(TEST_LAT, TEST_LON, payload, area="test_osm")
    candidate = result["candidates"][0]

    for key in ("category", "score", "uid", "where", "combined", "roadname"):
        assert key in candidate
    assert result["taxi_label"]["label"] == "伏見通（御園座付近）"
