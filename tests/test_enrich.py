"""layer_mapping 補完（enrich, Phase R6）のテスト。"""

from steel_estimator import enrich
from steel_estimator import layer_mapping as lmap
from steel_estimator import price_analysis as pa
from steel_estimator import candidate_prices as cp
from steel_estimator import cli
from steel_estimator import csv_utils as cu
from steel_estimator.models import MaterialCategory as C


def mrow(**kw):
    base = {f: "" for f in lmap.MAPPING_FIELDS}
    base["enabled"] = "true"
    base["waste_rate"] = "1.0"
    base.update(kw)
    return base


def summ(**kw):
    base = {f: "" for f in cp.SUMMARY_FIELDS}
    base["sample_count"] = 3
    base["usable_as_base_price"] = "true"
    base["candidate_class"] = cp.CLASS_BASE
    base.update(kw)
    return base


MASTER = pa.build_practical_master([
    summ(material_category=C.SQUARE_PIPE, material_grade="STKR",
         spec_key="square_pipe|STKR|50x50|t2.3|L6000",
         normalized_spec="STKR_50x50_t2.3_L6000",
         latest_unit_price="5020", latest_quote_date="2025-11-12",
         price_unit="個", vendor_name="東鋼材", confidence="0.9",
         needs_review="false"),
])


def test_enrich_does_not_mutate_original():  # 必須12
    original = [mrow(layer_name="架台::角パイプ_50", material_category=C.SQUARE_PIPE,
                     width_mm="50")]
    snapshot = dict(original[0])
    enrich.enrich_mapping(original, [], MASTER)
    # 入力行は一切変更されない
    assert original[0] == snapshot
    assert original[0]["unit_price"] == ""


def test_enrich_adds_review_required_note():  # 必須13
    rows = mrow(layer_name="架台::角パイプ_50", material_category=C.SQUARE_PIPE, width_mm="50")
    out = enrich.enrich_mapping([rows], [], MASTER)
    assert enrich.ENRICH_NOTE in out[0]["notes"]


def test_enrich_fills_only_empty_fields():
    rows = mrow(layer_name="架台::角パイプ_50", material_category=C.SQUARE_PIPE,
                width_mm="50", material_grade="既存値")
    out = enrich.enrich_mapping([rows], [], MASTER)
    # 既存の material_grade は上書きされない
    assert out[0]["material_grade"] == "既存値"


def test_enrich_unit_price_marked_review():
    rows = mrow(layer_name="架台::角パイプ_50", material_category=C.SQUARE_PIPE, width_mm="50")
    out = enrich.enrich_mapping([rows], [], MASTER)
    if out[0]["unit_price"]:  # 単価が補完された場合
        assert out[0]["price_source"].startswith("auto:")
        assert "要確認" in out[0]["notes"]


def test_enrich_cli_does_not_overwrite_source(tmp_path):
    mapping_csv = tmp_path / "mapping.csv"
    summary_csv = tmp_path / "layer_summary.csv"
    master_csv = tmp_path / "master.csv"
    out_csv = tmp_path / "enriched.csv"

    lmap.write_mapping(str(mapping_csv), [
        mrow(layer_name="架台::角パイプ_50", material_category=C.SQUARE_PIPE, width_mm="50"),
    ])
    cu.write_dicts(str(summary_csv), ["layer_name"], [{"layer_name": "架台::角パイプ_50"}])
    pa.write_practical_master(str(master_csv), MASTER)

    before = mapping_csv.read_text(encoding="utf-8-sig")
    rc = cli.main([
        "enrich-layer-mapping",
        "--mapping", str(mapping_csv),
        "--summary", str(summary_csv),
        "--practical-master", str(master_csv),
        "--out", str(out_csv),
    ])
    assert rc == 0
    assert out_csv.exists()
    # 元mappingファイルは変更されていない
    assert mapping_csv.read_text(encoding="utf-8-sig") == before
