"""候補単価マスター生成のテスト。"""

import os

from steel_estimator import candidate_prices as cp
from steel_estimator.models import MaterialCategory as C


def rec(**kw):
    base = {
        "vendor_name": "東鋼材", "material_category": "", "material_grade": "",
        "item_name_original": "", "raw_text_line": "", "notes": "", "shape_token": "",
        "diameter_mm": None, "thickness_mm": None, "width_mm": None, "height_mm": None,
        "length_mm": None, "plate_width_mm": None, "plate_height_mm": None,
        "unit_price": None, "amount": None, "quantity": None, "quote_date": "",
        "source_pdf_filename": "x.pdf", "page_number": 1, "needs_review": 0, "unit": "個",
        "dimension_text_original": "",
    }
    base.update(kw)
    return base


def _classes(rows):
    return {r["spec_text"] or r["normalized_spec"]: r["candidate_class"] for r in rows}


def test_vendor_filter():  # 必須1
    records = [
        rec(vendor_name="東鋼材", material_category=C.ROUND_PIPE, diameter_mm=48.6),
        rec(vendor_name="株式会社あずま工房", material_category=C.ROUND_PIPE, diameter_mm=60),
        rec(vendor_name="", material_category=C.PLATE, thickness_mm=6),
    ]
    rows, _ = cp.build_candidates(records, vendor="東鋼材")
    assert len(rows) == 1
    assert rows[0]["vendor_name"] == "東鋼材"


def test_processed_excluded_from_base():  # 必須2
    records = [
        rec(material_category=C.ROUND_PIPE, item_name_original="丸パイプ R曲げ",
            diameter_mm=76.3, thickness_mm=3.2, length_mm=500, unit_price=12590),
        rec(material_category=C.PLATE, item_name_original="型切", thickness_mm=6,
            plate_width_mm=300, plate_height_mm=300, unit_price=720),
    ]
    rows, _ = cp.build_candidates(records)
    for r in rows:
        assert r["candidate_class"] == cp.CLASS_PROCESSED
        assert r["usable_as_base_price"] == "false"


def test_round_pipe_base():  # 必須3
    rows, _ = cp.build_candidates([rec(
        material_category=C.ROUND_PIPE, material_grade="STK400",
        item_name_original="丸パイプ", diameter_mm=48.6, thickness_mm=2.3,
        length_mm=6000, unit_price=2630)])
    assert rows[0]["candidate_class"] == cp.CLASS_BASE
    assert rows[0]["usable_as_base_price"] == "true"


def test_square_pipe_base():  # 必須4
    rows, _ = cp.build_candidates([rec(
        material_category=C.SQUARE_PIPE, material_grade="STKR",
        item_name_original="角パイプ", width_mm=50, height_mm=50,
        thickness_mm=2.3, length_mm=6000)])
    assert rows[0]["candidate_class"] == cp.CLASS_BASE


def test_plate_material():  # 必須5
    rows, _ = cp.build_candidates([rec(
        material_category=C.PLATE, material_grade="SS400",
        item_name_original="PL", thickness_mm=6)])
    assert rows[0]["candidate_class"] == cp.CLASS_PLATE
    assert rows[0]["spec_key"] == "plate|SS400|t6"
    assert rows[0]["normalized_spec"] == "SS400_PL_t6"


def test_hbeam_jis():  # 必須6
    rows, _ = cp.build_candidates([rec(
        material_category=C.H_BEAM, material_grade="SS400",
        item_name_original="H形鋼", width_mm=100, height_mm=100,
        thickness_mm=6, length_mm=3000)])
    assert rows[0]["candidate_class"] == cp.CLASS_JIS
    assert rows[0]["needs_review"] == "true"


def test_unknown_stays_unknown():  # 必須7
    rows, _ = cp.build_candidates([rec(
        material_category=C.UNKNOWN, item_name_original="謎の品目")])
    assert rows[0]["candidate_class"] == cp.CLASS_UNKNOWN


def test_normalized_spec_and_key():  # 必須8
    rows, _ = cp.build_candidates([rec(
        material_category=C.ROUND_PIPE, material_grade="STK400",
        diameter_mm=48.6, thickness_mm=2.3, length_mm=6000)])
    assert rows[0]["normalized_spec"] == "STK400_D48.6_t2.3_L6000"
    assert rows[0]["spec_key"] == "round_pipe|STK400|D48.6|t2.3|L6000"


def test_missing_dims_needs_review():
    rows, _ = cp.build_candidates([rec(
        material_category=C.ROUND_PIPE, material_grade="STK400", diameter_mm=48.6)])
    assert rows[0]["needs_review"] == "true"  # t,L 欠落


def test_aggregate_stats():  # 必須9
    records = [
        rec(material_category=C.ROUND_PIPE, material_grade="STK400", diameter_mm=48.6,
            thickness_mm=2.3, length_mm=6000, unit_price=2600, quote_date="2023-01-01"),
        rec(material_category=C.ROUND_PIPE, material_grade="STK400", diameter_mm=48.6,
            thickness_mm=2.3, length_mm=6000, unit_price=2800, quote_date="2023-06-01"),
        rec(material_category=C.ROUND_PIPE, material_grade="STK400", diameter_mm=48.6,
            thickness_mm=2.3, length_mm=6000, unit_price=3000, quote_date="2024-01-01"),
    ]
    rows, _ = cp.build_candidates(records)
    summ = cp.aggregate(rows)
    assert len(summ) == 1
    s = summ[0]
    assert s["sample_count"] == 3
    assert s["latest_unit_price"] == "3000"      # 最新(2024)
    assert s["latest_quote_date"] == "2024-01-01"
    assert s["median_unit_price"] == "2800"
    assert s["min_unit_price"] == "2600"
    assert s["max_unit_price"] == "3000"


def test_outlier_warning():  # 必須10
    records = [
        rec(material_category=C.ROUND_PIPE, material_grade="STK400", diameter_mm=48.6,
            thickness_mm=2.3, length_mm=6000, unit_price=1000, quote_date="2023-01-01"),
        rec(material_category=C.ROUND_PIPE, material_grade="STK400", diameter_mm=48.6,
            thickness_mm=2.3, length_mm=6000, unit_price=3000, quote_date="2023-06-01"),
    ]
    summ = cp.aggregate(cp.build_candidates(records)[0])
    assert "max/min" in summ[0]["warning"]


def test_sample_count_one_warning():  # 必須11
    rows, _ = cp.build_candidates([rec(
        material_category=C.ROUND_PIPE, material_grade="STK400", diameter_mm=48.6,
        thickness_mm=2.3, length_mm=6000, unit_price=2600, quote_date="2023-01-01")])
    summ = cp.aggregate(rows)
    assert "サンプル1件" in summ[0]["warning"]


def test_report_markdown():  # 必須12
    rows, _ = cp.build_candidates([
        rec(material_category=C.ROUND_PIPE, material_grade="STK400", diameter_mm=48.6,
            thickness_mm=2.3, length_mm=6000, unit_price=2600, quote_date="2023-01-01"),
        rec(material_category=C.ROUND_PIPE, item_name_original="丸パイプ R曲げ",
            diameter_mm=76.3, thickness_mm=3.2, length_mm=500, unit_price=12590),
    ])
    summ = cp.aggregate(rows)
    md = cp.build_report(rows, summ, "東鋼材", "2026-05-31")
    assert "候補単価レポート" in md
    assert "base_material" in md
    assert "processed_item" in md


def test_bom_output(tmp_path):  # 必須17
    rows, _ = cp.build_candidates([rec(
        material_category=C.ROUND_PIPE, material_grade="STK400", diameter_mm=48.6,
        thickness_mm=2.3, length_mm=6000, unit_price=2600)])
    p = tmp_path / "cand.csv"
    cp.write_candidates(str(p), rows)
    with open(p, "rb") as f:
        assert f.read(3) == b"\xef\xbb\xbf"
