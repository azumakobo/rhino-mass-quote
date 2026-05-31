"""候補単価DB分析（Phase R6）のテスト。"""

import os

from steel_estimator import candidate_prices as cp
from steel_estimator import price_analysis as pa
from steel_estimator import cli
from steel_estimator import csv_utils as cu
from steel_estimator.models import MaterialCategory as C


def summ(**kw):
    base = {f: "" for f in cp.SUMMARY_FIELDS}
    base["sample_count"] = 1
    base["usable_as_base_price"] = "true"
    base["candidate_class"] = cp.CLASS_BASE
    base.update(kw)
    return base


def cand(**kw):
    base = {f: "" for f in cp.CANDIDATE_FIELDS}
    base.update(kw)
    return base


# 角パイプ定尺（断面・長さ揃い → m単価/kg単価が出るはず）
SQ = summ(material_category=C.SQUARE_PIPE, material_grade="STKR",
          spec_key="square_pipe|STKR|50x50|t2.3|L6000",
          normalized_spec="STKR_50x50_t2.3_L6000",
          latest_unit_price="5020", median_unit_price="4900",
          average_unit_price="4950", sample_count=3,
          latest_quote_date="2025-11-12", price_unit="個", vendor_name="東鋼材",
          confidence="0.9", needs_review="false")

PROC = summ(material_category=C.PLATE, candidate_class=cp.CLASS_PROCESSED,
            usable_as_base_price="false",
            spec_key="plate|SS400|t6|300x300", latest_unit_price="720",
            needs_review="true")

JIS = summ(material_category=C.H_BEAM, candidate_class=cp.CLASS_JIS,
           usable_as_base_price="false",
           spec_key="h_beam|SS400|100x100|t6|L6000", latest_unit_price="8910")


def test_price_per_m_from_stock():  # 必須4
    master = pa.build_practical_master([SQ])
    row = master[0]
    # 5020円 / 6m = 836.7
    assert row["price_per_m"] != ""
    assert abs(float(row["price_per_m"]) - 5020 / 6.0) < 1.0


def test_price_per_kg_from_weight():  # 必須5
    master = pa.build_practical_master([SQ])
    row = master[0]
    assert row["price_per_kg"] != ""
    assert float(row["price_per_kg"]) > 0
    assert row["estimated_weight_kg_per_stock"] != ""


def test_processed_is_not_for_base():  # 必須6
    master = pa.build_practical_master([PROC])
    assert master[0]["usability"] == pa.U_NOT_BASE


def test_jis_needs_master():
    master = pa.build_practical_master([JIS])
    assert master[0]["usability"] == pa.U_NEEDS_JIS
    # JIS形鋼は重量換算しない（price_per_kgは空）
    assert master[0]["price_per_kg"] == ""


def test_ready_usability():
    master = pa.build_practical_master([SQ])
    # サンプル3件・換算可・needs_review=false → ready
    assert master[0]["usability"] == pa.U_READY


def test_short_piece_no_m_price():
    short = summ(material_category=C.ROUND_BAR, material_grade="S45C",
                 spec_key="round_bar|S45C|D100|L70", latest_unit_price="16750",
                 sample_count=2, needs_review="false")
    master = pa.build_practical_master([short])
    # L70mm は切断材 → m単価は出さない（誤誘導防止）、kg単価のみ
    assert master[0]["price_per_m"] == ""
    assert master[0]["usability"] != pa.U_READY


def test_classify_plate():  # 必須7（R6.1再設計: 6分類）
    assert pa.classify_plate("曲げ加工") == pa.PLATE_BENT
    assert pa.classify_plate("型切") == pa.PLATE_SHAPED          # 型切→shaped_cut_plate
    assert pa.classify_plate("切板") == pa.PLATE_RECT            # 切板→rectangular_cut_plate
    assert pa.classify_plate("定尺 鋼板") == pa.PLATE_RAW
    assert pa.classify_plate("謎の板") == pa.PLATE_UNKNOWN
    # 加工キーワードはあるが寸法欠落 → plate_processing_only
    assert pa.classify_plate("型切", has_thickness=False, has_wh=False) == pa.PLATE_PROCESSING


def test_plate_reference_built():  # 必須8
    rows = pa.build_plate_reference([
        cand(material_category=C.PLATE, material_grade="SS400",
             spec_key="plate|SS400|t6|300x300", spec_text="切板",
             quantity="6", unit_price="720", amount="4320",
             quote_date="2025-01-01", source_pdf="a.pdf"),
    ])
    assert len(rows) == 1
    r = rows[0]
    assert r["plate_class"] == pa.PLATE_RECT
    assert r["estimated_weight_kg_total"] != ""
    assert r["price_per_kg"] != ""
    assert r["price_per_m2"] != ""


def _katagiri_row():
    # 型切 / SS400 / t4.5 / 549×549 / 数量4 / 単価2780 / 金額11120
    return cand(material_category=C.PLATE, material_grade="SS400",
                spec_key="plate|SS400|t4.5|549x549", spec_text="型切",
                notes="型切(異形): 寸法は外接矩形", quantity="4",
                unit_price="2780", amount="11120", quote_date="2025-11-12",
                source_pdf="b.pdf", source_page="1")


def test_katagiri_area_weight_price():  # 必須R6.1-1
    rows = pa.build_plate_reference([_katagiri_row()])
    r = rows[0]
    # area_each = 549*549/1e6 = 0.301401 m2
    assert abs(float(r["estimated_area_m2_each"]) - 0.301401) < 1e-3
    # weight_total = area_each*t*density*qty = 0.301401*4.5*7.85*4 ≈ 42.59 kg
    assert abs(float(r["estimated_weight_kg_total"]) - 42.59) < 0.5
    # price_per_kg = amount / weight_total ≈ 11120/42.59 ≈ 261
    assert abs(float(r["price_per_kg"]) - 261) < 5


def test_katagiri_not_base_but_reference():  # 必須R6.1-2, 3
    r = pa.build_plate_reference([_katagiri_row()])[0]
    assert r["usable_as_base_price"] == "false"
    assert r["usable_as_reference"] == "true"


def test_katagiri_is_shaped_cut_plate():  # 必須R6.1-4
    r = pa.build_plate_reference([_katagiri_row()])[0]
    assert r["plate_class"] == pa.PLATE_SHAPED


def test_kiriita_is_rectangular():  # 必須R6.1-5
    r = pa.build_plate_reference([
        cand(material_category=C.PLATE, material_grade="SS400",
             spec_key="plate|SS400|t6|300x300", spec_text="切板",
             quantity="6", unit_price="720", amount="4320"),
    ])[0]
    assert r["plate_class"] == pa.PLATE_RECT


def test_plate_reference_summary_generated():  # 必須R6.1-6
    refs = pa.build_plate_reference([_katagiri_row(), _katagiri_row()])
    summ_rows = pa.build_plate_reference_summary(refs)
    assert len(summ_rows) >= 1
    s = summ_rows[0]
    assert s["material_grade"] == "SS400"
    assert s["thickness_mm"] == "4.5"
    assert s["median_price_per_kg"] != ""
    assert s["usable_as_reference"] == "true"
    assert s["warning"]  # 必須warning


def test_practical_master_includes_plate_reference():  # 必須R6.1-9
    refs = pa.build_plate_reference([_katagiri_row()])
    summ_rows = pa.build_plate_reference_summary(refs)
    master = pa.build_practical_master([SQ], summ_rows)
    prefs = [m for m in master if m["candidate_class"] == "plate_reference"]
    assert len(prefs) >= 1
    p = prefs[0]
    assert p["material_category"] == C.PLATE
    assert p["usable_as_base_price"] == "false"
    assert p["usable_as_reference"] == "true"
    assert p["price_per_kg"] != ""
    assert p["warning"]


def test_aluminum_density():
    # アルミ(A5052)は鉄密度7.85ではなく2.70で計算され warning が付く
    r = pa.build_plate_reference([
        cand(material_category=C.PLATE, material_grade="A5052",
             spec_key="plate|A5052|t2|510x810", spec_text="天板 アルミ",
             quantity="1", unit_price="7730", amount="7730"),
    ])[0]
    assert "アルミ" in r["warning"]
    # 重量: 0.510*0.810*2*2.70 ≈ 2.23 kg（鉄なら6.5kg）
    assert abs(float(r["estimated_weight_kg_total"]) - 2.23) < 0.2


def test_category_overview_built():  # 必須2 (builder)
    cands = [
        cand(material_category=C.SQUARE_PIPE, candidate_class=cp.CLASS_BASE, unit_price="5020"),
        cand(material_category=C.PLATE, candidate_class=cp.CLASS_PROCESSED, unit_price="720"),
    ]
    tables = pa.build_tables(cands, [SQ, PROC], pa.build_practical_master([SQ, PROC]),
                             pa.build_plate_reference(cands))
    assert "category_overview" in tables
    co = {r["material_category"]: r for r in tables["category_overview"]}
    assert co[C.SQUARE_PIPE]["base_material"] == 1
    assert co[C.PLATE]["processed_item"] == 1


def test_unit_conversion_excludes_plate():
    master = pa.build_practical_master([SQ, PROC])
    tables = pa.build_tables([], [SQ, PROC], master, [])
    cats = {r["material_category"] for r in tables["unit_conversion_candidates"]}
    assert C.PLATE not in cats  # 板材は生材換算表に出さない


# ---- CLI レベルの生成テスト ----

def _write(path, fields, rows):
    cu.write_dicts(path, fields, rows)


def test_analyze_cli_generates_outputs(tmp_path):  # 必須1, 2, 3, 8
    cand_csv = tmp_path / "cand.csv"
    summ_csv = tmp_path / "summ.csv"
    _write(str(cand_csv), cp.CANDIDATE_FIELDS, [
        cand(material_category=C.SQUARE_PIPE, candidate_class=cp.CLASS_BASE,
             spec_key="square_pipe|STKR|50x50|t2.3|L6000", unit_price="5020"),
        cand(material_category=C.PLATE, candidate_class=cp.CLASS_PROCESSED,
             spec_key="plate|SS400|t6|300x300", spec_text="切板", unit_price="720",
             amount="720", quote_date="2025-01-01"),
    ])
    _write(str(summ_csv), cp.SUMMARY_FIELDS, [SQ, PROC])

    report = tmp_path / "report.md"
    tables_dir = tmp_path / "tables"
    master_out = tmp_path / "practical_master.csv"
    plate_out = tmp_path / "plate_ref.csv"

    rc = cli.main([
        "analyze-candidate-prices",
        "--candidates", str(cand_csv),
        "--summary", str(summ_csv),
        "--out", str(report),
        "--tables-out", str(tables_dir),
        "--practical-master-out", str(master_out),
        "--plate-reference-out", str(plate_out),
    ])
    assert rc == 0
    assert report.exists()                                    # 必須1
    assert (tables_dir / "category_overview.csv").exists()    # 必須2
    assert master_out.exists()                                # 必須3
    assert plate_out.exists()                                 # 必須8
    # 実用単価マスターに price_per_m 列が入っていること
    master_rows = cu.read_dicts(str(master_out))
    assert any(r["price_per_m"] for r in master_rows)
