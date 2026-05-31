"""layer_mapping への候補単価提案のテスト。"""

from steel_estimator import layer_mapping as lmap
from steel_estimator import price_suggestions as ps
from steel_estimator import candidate_prices as cp
from steel_estimator.models import MaterialCategory as C


def mrow(**kw):
    base = {f: "" for f in lmap.MAPPING_FIELDS}
    base["enabled"] = "true"
    base["waste_rate"] = "1.0"
    base.update(kw)
    return base


def srow(**kw):
    base = {f: "" for f in cp.SUMMARY_FIELDS}
    base["usable_as_base_price"] = "true"
    base["sample_count"] = 1
    base.update(kw)
    return base


CANDIDATES = [
    srow(material_category=C.SQUARE_PIPE, material_grade="STKR",
         spec_key="square_pipe|STKR|50x50|t2.3|L6000",
         normalized_spec="STKR_50x50_t2.3_L6000",
         candidate_class=cp.CLASS_BASE, latest_unit_price="3880",
         latest_quote_date="2024-01-01", price_unit="個", vendor_name="東鋼材"),
    srow(material_category=C.ROUND_PIPE, material_grade="STK400",
         spec_key="round_pipe|STK400|D48.6|t2.3|L6000",
         normalized_spec="STK400_D48.6_t2.3_L6000",
         candidate_class=cp.CLASS_BASE, latest_unit_price="2630",
         latest_quote_date="2024-01-01", price_unit="個", vendor_name="東鋼材"),
    # 加工品（提案対象外）
    srow(material_category=C.ROUND_PIPE, material_grade="STK400",
         spec_key="round_pipe|STK400|D76.3|t3.2|L500",
         candidate_class=cp.CLASS_PROCESSED, usable_as_base_price="false",
         latest_unit_price="12590", latest_quote_date="2025-01-01"),
]


def test_exact_match():  # 必須13
    m = [mrow(layer_name="角パイプ", material_category=C.SQUARE_PIPE, material_grade="STKR",
             width_mm="50", height_mm="50", thickness_mm="2.3")]
    out = ps.suggest_for_mapping(m, CANDIDATES)
    assert out[0]["match_level"] == "exact"
    assert out[0]["suggested_unit_price"] == "3880"
    assert out[0]["suggested_vendor"] == "東鋼材"


def test_close_match():  # 必須14
    # 49x49 t2.3 → 50x50 t2.3 に近い（15%以内）
    m = [mrow(layer_name="角パイプ", material_category=C.SQUARE_PIPE,
             width_mm="49", height_mm="49", thickness_mm="2.3")]
    out = ps.suggest_for_mapping(m, CANDIDATES)
    assert out[0]["match_level"] == "close"
    assert out[0]["suggested_unit_price"] == "3880"


def test_none_match():  # 必須15
    m = [mrow(layer_name="ボルト", material_category=C.ROUND_BAR, diameter_mm="10")]
    out = ps.suggest_for_mapping(m, CANDIDATES)
    assert out[0]["match_level"] == "none"
    assert out[0]["suggested_unit_price"] == ""


def test_processed_not_suggested():
    # round_pipe D76.3 は processed のみ → 提案されない（usable=falseを除外）
    m = [mrow(layer_name="丸パイプ", material_category=C.ROUND_PIPE, material_grade="STK400",
             diameter_mm="76.3", thickness_mm="3.2")]
    out = ps.suggest_for_mapping(m, CANDIDATES)
    # D48.6 とは寸法が離れるため category_only 以下、12590(加工品)は採用されない
    assert out[0]["suggested_unit_price"] != "12590"


def test_not_auto_applied_to_mapping():  # 必須16
    m = [mrow(layer_name="角パイプ", material_category=C.SQUARE_PIPE, material_grade="STKR",
             width_mm="50", height_mm="50", thickness_mm="2.3")]
    before = dict(m[0])
    out = ps.suggest_for_mapping(m, CANDIDATES)
    # 元 mapping 行は変更されない（unit_price 空のまま）
    assert m[0] == before
    assert m[0]["unit_price"] == ""
    # 提案は別レコードに出る
    assert out[0]["suggested_unit_price"] == "3880"
    assert "提案のみ" in out[0]["notes"]


def test_match_level_counts():
    m = [
        mrow(layer_name="角パイプ", material_category=C.SQUARE_PIPE, material_grade="STKR",
             width_mm="50", height_mm="50", thickness_mm="2.3"),
        mrow(layer_name="ボルト", material_category=C.ROUND_BAR, diameter_mm="10"),
    ]
    out = ps.suggest_for_mapping(m, CANDIDATES)
    counts = ps.match_level_counts(out)
    assert counts["exact"] == 1
    assert counts["none"] == 1


def test_exact_without_length():  # 必須10
    # 断面・材質は一致するが、定尺長が候補(L6000)とmapping(4000)で食い違う
    m = [mrow(layer_name="角パイプ", material_category=C.SQUARE_PIPE, material_grade="STKR",
             width_mm="50", height_mm="50", thickness_mm="2.3", stock_length_mm="4000")]
    out = ps.suggest_for_mapping(m, CANDIDATES)
    assert out[0]["match_level"] == "exact_without_length"
    assert out[0]["suggested_unit_price"] == "3880"


def test_dimension_match_grade_unspecified():  # 必須11
    # 材質未指定だが断面寸法(50x50 t2.3)が厳密一致 → dimension_match
    m = [mrow(layer_name="角パイプ", material_category=C.SQUARE_PIPE,
             width_mm="50", height_mm="50", thickness_mm="2.3")]
    out = ps.suggest_for_mapping(m, CANDIDATES)
    assert out[0]["match_level"] == "dimension_match"
    assert out[0]["suggested_unit_price"] == "3880"


def test_dimension_match_partial_dims():  # 角パイプ_50（幅のみ既知）
    m = [mrow(layer_name="角パイプ_50", material_category=C.SQUARE_PIPE, width_mm="50")]
    out = ps.suggest_for_mapping(m, CANDIDATES)
    assert out[0]["match_level"] == "dimension_match"


def test_match_failure_analysis(tmp_path):  # 必須9
    m = [mrow(layer_name="角パイプ_50", material_category=C.SQUARE_PIPE, width_mm="50")]
    rows = ps.build_match_failure_analysis(m, CANDIDATES)
    assert rows[0]["layer_name"] == "角パイプ_50"
    assert rows[0]["current_match_level"] == "dimension_match"
    assert int(rows[0]["candidate_count_same_category"]) >= 1
    assert "material_grade" in rows[0]["missing_fields"]
    p = tmp_path / "match_failure_analysis.csv"
    ps.write_match_failure_analysis(str(p), rows)
    assert p.exists()


def test_match_failure_no_category():
    # material_category未設定 → 修正提案は material_category を最優先
    m = [mrow(layer_name="補助線")]
    rows = ps.build_match_failure_analysis(m, CANDIDATES)
    assert "material_category" in rows[0]["recommended_mapping_fix"]


# ---- plate_reference フォールバック（R6.1） ----

PLATE_REFS = [
    {"material_grade": "SS400", "thickness_mm": "6", "plate_class": "shaped_cut_plate",
     "median_price_per_kg": "250", "latest_quote_date": "2025-11-12",
     "confidence": "0.4", "usable_as_reference": "true"},
    {"material_grade": "SS400", "thickness_mm": "9", "plate_class": "rectangular_cut_plate",
     "median_price_per_kg": "240", "latest_quote_date": "2025-11-12",
     "confidence": "0.4", "usable_as_reference": "true"},
]


def test_plate_reference_same_thickness():  # 必須R6.1-7
    # raw_plate候補なし、鉄板t6 → 同板厚の型切参考を提示
    m = [mrow(layer_name="鉄板6mm", material_category=C.PLATE, thickness_mm="6")]
    out = ps.suggest_for_mapping(m, CANDIDATES, plate_reference_rows=PLATE_REFS)
    assert out[0]["match_level"] == "plate_reference_same_thickness"
    assert out[0]["suggested_unit_price"] == "250"
    assert out[0]["suggested_price_unit"] == "kg"


def test_plate_reference_near_thickness():
    # t7 → ±25%以内に t6/t9 → 近似板厚で提示
    m = [mrow(layer_name="鉄板7mm", material_category=C.PLATE, thickness_mm="7")]
    out = ps.suggest_for_mapping(m, CANDIDATES, plate_reference_rows=PLATE_REFS)
    assert out[0]["match_level"] == "plate_reference_near_thickness"


def test_plate_reference_warning_always():  # 必須R6.1-8
    m = [mrow(layer_name="鉄板6mm", material_category=C.PLATE, thickness_mm="6")]
    out = ps.suggest_for_mapping(m, CANDIDATES, plate_reference_rows=PLATE_REFS)
    assert "型切" in out[0]["warning"]
    assert "要確認" in out[0]["warning"]
    assert out[0]["needs_review"] == "true"


def test_plate_reference_counts():
    m = [mrow(layer_name="鉄板6mm", material_category=C.PLATE, thickness_mm="6")]
    out = ps.suggest_for_mapping(m, CANDIDATES, plate_reference_rows=PLATE_REFS)
    counts = ps.match_level_counts(out)
    assert counts["plate_reference_same_thickness"] == 1
