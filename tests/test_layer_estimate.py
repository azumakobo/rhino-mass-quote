"""calc_type 別の計算・needs_review・warning・総括のテスト。"""

import pytest

from steel_estimator import layer_mapping as lmap
from steel_estimator import layer_estimate as lest


def mrow(**kw):
    base = {f: "" for f in lmap.MAPPING_FIELDS}
    base["enabled"] = "true"
    base["waste_rate"] = "1.0"
    base.update(kw)
    return base


def srow(name, **kw):
    base = {
        "layer_name": name, "object_count": "", "total_area_m2": "",
        "total_volume_mm3": "", "total_curve_length_m": "",
    }
    base.update(kw)
    return base


def _one(summary, mapping):
    results, _ = lest.estimate_layers(summary, mapping)
    return results[0]


def test_area_to_weight():  # 必須5
    s = [srow("鉄板6mm", total_area_m2="2.0")]
    m = [mrow(layer_name="鉄板6mm", calc_type="area_to_weight", thickness_mm="6",
             density_g_cm3="7.85", unit_price="150", price_unit="kg")]
    r = _one(s, m)
    assert r["estimated_weight_kg"] == pytest.approx(94.2, abs=0.01)
    assert r["estimated_amount"] == pytest.approx(14130, abs=1)
    assert r["accuracy_level"] == "manual_mapping"
    assert r["needs_review"] == "false"


def test_volume_to_weight():  # 必須6
    s = [srow("ソリッド", total_volume_mm3="1000000")]
    m = [mrow(layer_name="ソリッド", calc_type="volume_to_weight",
             density_g_cm3="7.85", unit_price="300", price_unit="kg")]
    r = _one(s, m)
    assert r["estimated_weight_kg"] == pytest.approx(7.85, abs=0.01)
    assert r["estimated_amount"] == pytest.approx(2355, abs=1)


def test_curve_length_to_stock():  # 必須7
    s = [srow("角パイプ", total_curve_length_m="18")]
    m = [mrow(layer_name="角パイプ", calc_type="curve_length_to_stock",
             stock_length_mm="6000", unit_price="3880", price_unit="stock")]
    r = _one(s, m)
    assert r["adjusted_quantity"] == 3   # ceil(18000/6000*1.0)
    assert r["estimated_amount"] == pytest.approx(11640, abs=1)


def test_curve_length_to_stock_default_length_warns():  # 必須(stock未指定→6000+warning)
    s = [srow("角パイプ", total_curve_length_m="7")]
    m = [mrow(layer_name="角パイプ", calc_type="curve_length_to_stock",
             unit_price="3880", price_unit="stock")]  # stock_length_mm 空
    r = _one(s, m)
    assert r["adjusted_quantity"] == 2   # ceil(7000/6000)=2
    assert "stock_length_mm" in r["warning"]


def test_curve_length_to_meter():  # 必須8
    s = [srow("手すり", total_curve_length_m="10")]
    m = [mrow(layer_name="手すり", calc_type="curve_length_to_meter",
             unit_price="1200", price_unit="m", waste_rate="1.0")]
    r = _one(s, m)
    assert r["adjusted_quantity"] == pytest.approx(10.0)
    assert r["estimated_amount"] == pytest.approx(12000, abs=1)


def test_object_count():  # 必須9
    s = [srow("ボルト", object_count="24")]
    m = [mrow(layer_name="ボルト", calc_type="object_count",
             unit_price="80", price_unit="個")]
    r = _one(s, m)
    assert r["adjusted_quantity"] == 24
    assert r["estimated_amount"] == pytest.approx(1920)


def test_manual_quantity():  # 必須10
    s = [srow("手入力")]
    m = [mrow(layer_name="手入力", calc_type="manual_quantity",
             quantity_override="5", unit_price="100")]
    r = _one(s, m)
    assert r["adjusted_quantity"] == pytest.approx(5.0)
    assert r["estimated_amount"] == pytest.approx(500)


def test_fixed_amount():  # 必須11
    s = [srow("塗装費")]
    m = [mrow(layer_name="塗装費", calc_type="fixed_amount", fixed_amount="20000")]
    r = _one(s, m)
    assert r["estimated_amount"] == pytest.approx(20000)
    assert r["accuracy_level"] == "fixed"
    assert r["needs_review"] == "false"


def test_ignore_layer():  # 必須12
    s = [srow("補助線", total_curve_length_m="5")]
    m = [mrow(layer_name="補助線", calc_type="ignore")]
    r = _one(s, m)
    assert r["source_type"] == "ignored"
    assert r["accuracy_level"] == "ignored"
    assert r["needs_review"] == "false"


def test_disabled_layer_is_ignored():
    s = [srow("鉄板", total_area_m2="2.0")]
    m = [mrow(layer_name="鉄板", calc_type="area_to_weight", enabled="false",
             thickness_mm="6", unit_price="150")]
    r = _one(s, m)
    assert r["accuracy_level"] == "ignored"


def test_unmapped_layer_needs_review():  # 必須13
    s = [srow("未登録レイヤー", total_area_m2="1.0")]
    m = []  # mapping なし
    results, _ = lest.estimate_layers(s, m)
    assert len(results) == 1
    r = results[0]
    assert r["layer_name"] == "未登録レイヤー"
    assert r["needs_review"] == "true"
    assert r["accuracy_level"] == "unknown"
    assert "mapping" in r["warning"]


def test_missing_unit_price_needs_review():  # 必須14
    s = [srow("鉄板", total_area_m2="2.0")]
    m = [mrow(layer_name="鉄板", calc_type="area_to_weight", thickness_mm="6")]  # unit_price 空
    r = _one(s, m)
    assert r["needs_review"] == "true"
    assert "unit_price" in r["warning"]
    assert r["estimated_amount"] in ("", None)


def test_missing_thickness_warns():  # 必須15
    s = [srow("鉄板", total_area_m2="2.0")]
    m = [mrow(layer_name="鉄板", calc_type="area_to_weight", unit_price="150")]  # thickness 空
    r = _one(s, m)
    assert "thickness" in r["warning"]
    assert r["needs_review"] == "true"


def test_price_unit_conflict_warns():  # 必須16
    s = [srow("鉄板", total_area_m2="2.0")]
    m = [mrow(layer_name="鉄板", calc_type="area_to_weight", thickness_mm="6",
             unit_price="150", price_unit="m")]  # area なのに m
    r = _one(s, m)
    assert "不整合" in r["warning"]


def test_estimate_summary_subtotals():  # 必須18
    s = [srow("鉄板", total_area_m2="2.0"), srow("塗装費")]
    m = [
        mrow(layer_name="鉄板", calc_type="area_to_weight", thickness_mm="6",
             density_g_cm3="7.85", unit_price="150", price_unit="kg"),
        mrow(layer_name="塗装費", calc_type="fixed_amount", fixed_amount="20000"),
    ]
    _, summ = lest.estimate_layers(s, m)
    by = {r["category"]: r for r in summ}
    assert by["material"]["subtotal_amount"] == pytest.approx(14130, abs=1)
    assert by["processing"]["subtotal_amount"] == pytest.approx(20000)
    assert "TOTAL(除ignored)" in by
    assert by["TOTAL(除ignored)"]["subtotal_amount"] == pytest.approx(34130, abs=1)


def test_waste_rate_applied():
    s = [srow("鉄板", total_area_m2="2.0")]
    m = [mrow(layer_name="鉄板", calc_type="area_to_weight", thickness_mm="6",
             density_g_cm3="7.85", unit_price="150", price_unit="kg", waste_rate="1.1")]
    r = _one(s, m)
    assert r["estimated_weight_kg"] == pytest.approx(103.62, abs=0.01)
