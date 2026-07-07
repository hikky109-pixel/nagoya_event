from pathlib import Path

from tools.location.road_aliases import infer_road_alias_from_result, match_road_aliases, normalize_intersection_name


def test_normalize_intersection_name_accepts_suffix_variants():
    assert normalize_intersection_name("桜通大津交差点") == normalize_intersection_name("桜通大津")
    assert normalize_intersection_name("錦通 大津 交差点") == normalize_intersection_name("錦通大津")


def test_sakuradori_known_intersection_matches_sakuradori():
    matches = match_road_aliases("桜通大津交差点")

    assert [match["name"] for match in matches] == ["桜通"]


def test_nishikidori_known_intersection_matches_nishikidori():
    matches = match_road_aliases("錦通本町")

    assert [match["name"] for match in matches] == ["錦通"]


def test_hirokojidori_known_intersection_matches_hirokojidori():
    matches = match_road_aliases("広小路伏見交差点")

    assert [match["name"] for match in matches] == ["広小路通"]


def test_unknown_intersection_returns_empty():
    assert match_road_aliases("未登録交差点") == []


def test_infer_keeps_multiple_road_candidates_without_adopting(tmp_path: Path):
    alias_path = tmp_path / "road_aliases.yml"
    alias_path.write_text(
        """version: 1
roads:
  - id: road_a
    name: A通
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
    assert inferred["reason"] == "複数道路に一致したため採用通り名は未確定"
