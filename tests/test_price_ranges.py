"""価格レンジマスター（Phase R6.3）のテスト。"""

from steel_estimator import price_ranges as prg
from steel_estimator import price_analysis as pa
from steel_estimator import candidate_prices as cp
from steel_estimator import layer_mapping as lmap
from steel_estimator import layer_estimate as lest
from steel_estimator import mapping_ui_models as ui
from steel_estimator import cli
from steel_estimator import csv_utils as cu
from steel_estimator.models import MaterialCategory as C


def cand(**kw):
    base = {f: "" for f in cp.CANDIDATE_FIELDS}
    base.update(kw)
    return base


def summ(**kw):
    base = {f: "" for f in cp.SUMMARY_FIELDS}
    base["sample_count"] = 3
    base["usable_as_base_price"] = "true"
    base["candidate_class"] = cp.CLASS_BASE
    base.update(kw)
    return base


def mrow(**kw):
    base = {f: "" for f in lmap.MAPPING_FIELDS}
    base["enabled"] = "true"
    base["waste_rate"] = "1.0"
    base.update(kw)
    return base


# 型切 t6 の参考価格行（kg単価を直接指定: median=270, max=280 を決定的に作る）
def _plate_ref_row(kg, m2="9000"):
    return {
        "material_grade": "SS400", "thickness_mm": "6",
        "plate_class": "rectangular_cut_plate",
        "price_per_kg": str(kg), "price_per_m2": str(m2),
        "quote_date": "2025-06-26", "usable_as_reference": "true",
    }


def _plate_refs_t6():
    return [_plate_ref_row(270), _plate_ref_row(270), _plate_ref_row(280)]


def test_plate_price_range_master_generated():  # 必須1
    rows = prg.build_plate_price_range_master(_plate_refs_t6(), tax_rate=0.10)
    assert rows
    assert all("median_price_per_kg_ex_tax" in r for r in rows)


def test_t6_median_270_inc_297():  # 必須2
    rows = prg.build_plate_price_range_master(_plate_refs_t6(), tax_rate=0.10)
    r = [x for x in rows if x["thickness_mm"] == "6"][0]
    assert r["median_price_per_kg_ex_tax"] == "270"
    assert r["median_price_per_kg_inc_tax"] == "297"


def test_t6_max_present():  # 必須3
    rows = prg.build_plate_price_range_master(_plate_refs_t6(), tax_rate=0.10)
    r = [x for x in rows if x["thickness_mm"] == "6"][0]
    assert float(r["max_price_per_kg_ex_tax"]) >= 270


def test_recommended_median_conservative_clamped():  # 必須4（安全側=中央値1.3〜2.0倍clamp）
    rows = prg.build_plate_price_range_master(_plate_refs_t6(), tax_rate=0.10)
    r = [x for x in rows if x["thickness_mm"] == "6"][0]
    # 通常 = 中央値
    assert r["recommended_price_per_kg_ex_tax"] == r["median_price_per_kg_ex_tax"]
    # 安全側 = clamp(最大値, 中央値×1.3, 中央値×2.0)。素の最大値ではない。
    med = float(r["median_price_per_kg_ex_tax"])
    mx = float(r["max_price_per_kg_ex_tax"])
    expected = prg.safe_conservative(med, mx)
    assert float(r["conservative_price_per_kg_ex_tax"]) == round(expected, 1)
    # 安全側は中央値の1.3〜2.0倍の範囲内
    assert med * 1.3 - 0.5 <= float(r["conservative_price_per_kg_ex_tax"]) <= med * 2.0 + 0.5
    assert r["default_pricing_mode"] == "median"
    assert r["editable"] == "true"


# 角パイプ 40x40 t2.3 L6000（min/median/max unit price を持つ practical master 行）
def _master_sqpipe():
    s = summ(material_category=C.SQUARE_PIPE, material_grade="SS400",
             spec_key="square_pipe|SS400|40x40|t2.3|L6000",
             normalized_spec="SS400_40x40_t2.3_L6000",
             latest_unit_price="4240", median_unit_price="4240",
             average_unit_price="4400", min_unit_price="4240",
             max_unit_price="4840", price_unit="個")
    return pa.build_practical_master([s], tax_rate=0.10)


def test_steel_shape_range_generated():  # 必須5
    rows = prg.build_steel_shape_price_range_master(_master_sqpipe(), tax_rate=0.10)
    assert rows
    assert rows[0]["material_category"] == C.SQUARE_PIPE


def test_sqpipe_median_max_price_per_m():  # 必須6, 7
    rows = prg.build_steel_shape_price_range_master(_master_sqpipe(), tax_rate=0.10)
    r = rows[0]
    # median m単価 = 4240 / 6 = 706.7
    assert abs(float(r["median_price_per_m_ex_tax"]) - 4240 / 6.0) < 1.0
    # max m単価 = 4840 / 6 = 806.7
    assert abs(float(r["max_price_per_m_ex_tax"]) - 4840 / 6.0) < 1.0


def test_round_pipe_classified_by_diameter_thickness():  # 必須8
    s = summ(material_category=C.ROUND_PIPE, material_grade="STK400",
             spec_key="round_pipe|STK400|D48.6|t2.3|L6000",
             normalized_spec="STK400_D48.6_t2.3_L6000",
             latest_unit_price="2630", median_unit_price="2630",
             min_unit_price="2630", max_unit_price="2900", price_unit="個")
    master = pa.build_practical_master([s], tax_rate=0.10)
    rows = prg.build_steel_shape_price_range_master(master, tax_rate=0.10)
    r = rows[0]
    assert r["diameter_mm"] == "48.6"
    assert r["thickness_mm"] == "2.3"


# ---- pricing_mode 解決（必須9,10,11） ----

def test_pricing_mode_median():  # 必須9
    row = mrow(pricing_mode="median", recommended_unit_price="270",
               conservative_unit_price="400")
    res = lmap.resolve_pricing(row)
    assert res["selected"] == 270.0
    assert res["basis"] == "median"


def test_pricing_mode_conservative():  # 必須10
    row = mrow(pricing_mode="conservative", recommended_unit_price="270",
               conservative_unit_price="400")
    res = lmap.resolve_pricing(row)
    assert res["selected"] == 400.0


def test_pricing_mode_manual():  # 必須11
    row = mrow(pricing_mode="manual", manual_unit_price="333",
               recommended_unit_price="270", conservative_unit_price="400")
    res = lmap.resolve_pricing(row)
    assert res["selected"] == 333.0


def test_pricing_legacy_returns_none():
    # pricing系もmanualもレンジも空 → None（従来フロー維持）
    assert lmap.resolve_pricing(mrow(unit_price="")) is None


# ---- estimate でレンジ金額（必須12,13） ----

def _estimate_with_range():
    m = [mrow(layer_name="床板", calc_type=lmap.CALC_OBJECT_COUNT,
              material_category=C.SQUARE_PIPE, price_unit="個",
              pricing_mode="median", recommended_unit_price="100",
              conservative_unit_price="150")]
    s = [{"layer_name": "床板", "object_count": "10"}]
    return lest.estimate_layers(s, m, tax_rate=0.10)


def test_what_costs_has_range_amounts():  # 必須12
    results, _ = _estimate_with_range()
    rows = lest.build_what_costs(results, 0.10)
    r = rows[0]
    assert r["selected_amount_ex_tax"] == "1000"        # 10 * 100
    assert r["recommended_amount_ex_tax"] == "1000"
    assert r["conservative_amount_ex_tax"] == "1500"    # 10 * 150
    assert r["conservative_amount_inc_tax"] == "1650"


def test_estimate_summary_has_range_subtotals():  # 必須13
    _, summary = _estimate_with_range()
    total = [s for s in summary if str(s["category"]).startswith("TOTAL")][0]
    assert total["selected_subtotal_ex_tax"] == 1000
    assert total["recommended_subtotal_ex_tax"] == 1000
    assert total["conservative_subtotal_ex_tax"] == 1500
    assert total["conservative_subtotal_inc_tax"] == 1650


# ---- UI（必須14） ----

def test_ui_handles_pricing_mode_and_manual():  # 必須14
    row = mrow(layer_name="床板", recommended_unit_price="270",
               conservative_unit_price="400")
    v = ui.pricing_view(row, 0.10)
    assert "median" in v["modes"] and "manual" in v["modes"]
    assert v["recommended"]["ex"] == 270 and v["recommended"]["inc"] == 297
    assert v["conservative"]["ex"] == 400


# ---- CLI 生成（必須1,5） ----

def test_cli_build_price_range_masters(tmp_path):
    plate_csv = tmp_path / "plate_ref.csv"
    master_csv = tmp_path / "master.csv"
    pa.write_plate_reference(str(plate_csv), _plate_refs_t6())
    pa.write_practical_master(str(master_csv), _master_sqpipe())
    rc = cli.main([
        "build-price-range-masters",
        "--plate-reference", str(plate_csv),
        "--practical-master", str(master_csv),
        "--out-dir", str(tmp_path),
        "--tax-rate", "0.10",
    ])
    assert rc == 0
    assert (tmp_path / "plate_price_range_master.csv").exists()
    assert (tmp_path / "steel_shape_price_range_master.csv").exists()
    assert (tmp_path / "price_range_report.md").exists()


# ---- 安全側単価のclamp（中央値1.3〜2.0倍） ----

def test_safe_conservative_examples():
    s = prg.safe_conservative
    assert s(300, 1420) == 600   # 外れ値→中央値×2.0で抑制
    assert s(300, 300) == 390    # 最大=中央値→中央値×1.3
    assert s(300, 350) == 390    # 1.3倍未満→中央値×1.3
    assert s(300, 500) == 500    # 範囲内→最大値採用
    assert s(300, 700) == 600    # 2.0倍超→中央値×2.0


def test_safe_conservative_bounds():
    # 常に [中央値×1.3, 中央値×2.0] に収まる
    for med, mx in [(100, 100), (100, 90), (250, 9999), (250, 250), (250, 400)]:
        v = prg.safe_conservative(med, mx)
        assert med * 1.3 <= v <= med * 2.0


def test_safe_conservative_none():
    assert prg.safe_conservative(None, 500) == 500   # 中央値不明は最大値そのまま
