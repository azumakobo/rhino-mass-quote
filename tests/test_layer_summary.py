"""layer_summary 集計と自動推定のテスト。"""

from steel_estimator import layer_summary as lsum
from steel_estimator.rhino_csv import RhinoObject


def _obj(**kw):
    base = dict(layer_name="L", object_count=1)
    base.update(kw)
    return RhinoObject(**base)


def test_build_summary_aggregates(tmp_path):
    """layer_summary を生成できる（必須2）。レイヤー単位で面積/長さ/体積を合算。"""
    objs = [
        _obj(layer_name="鉄板6mm", object_type="Surface", is_surface=True,
             object_area_mm2=1_000_000),
        _obj(layer_name="鉄板6mm", object_type="Surface", is_surface=True,
             object_area_mm2=1_000_000),
        _obj(layer_name="角パイプ_50", object_type="Curve", is_curve=True,
             object_curve_length_mm=6000),
        _obj(layer_name="角パイプ_50", object_type="Curve", is_curve=True,
             object_curve_length_mm=6000),
    ]
    rows = lsum.build_summary(objs)
    by = {r["layer_name"]: r for r in rows}
    assert by["鉄板6mm"]["total_area_m2"] == 2.0
    assert by["鉄板6mm"]["object_count"] == 2
    assert by["角パイプ_50"]["total_curve_length_m"] == 12.0
    # 自動推定（候補）
    assert by["鉄板6mm"]["suggested_calc_type"] == "area_to_weight"
    assert by["角パイプ_50"]["suggested_calc_type"] == "curve_length_to_stock"
    assert by["鉄板6mm"]["suggested_thickness_mm"] == 6.0


def test_suggest_for_layer_examples():
    assert lsum.suggest_for_layer("鉄板6mm")["suggested_calc_type"] == "area_to_weight"
    assert lsum.suggest_for_layer("丸パイプ手すり")["suggested_calc_type"] == "curve_length_to_stock"
    assert lsum.suggest_for_layer("ボルト類")["suggested_calc_type"] == "object_count"
    assert lsum.suggest_for_layer("補助線")["suggested_calc_type"] == "ignore"
    assert lsum.suggest_for_layer("塗装費")["suggested_calc_type"] == "fixed_amount"
    assert lsum.suggest_for_layer("曲げ加工")["suggested_calc_type"] == "fixed_amount"
    # 自動推定は確定値ではない＝material_categoryが空でも許容
    s = lsum.suggest_for_layer("謎レイヤー")
    assert s["suggested_calc_type"] == ""


def test_suggest_dimensions():
    d = lsum.suggest_dimensions("角パイプ_50")
    assert d["width_mm"] == 50.0
    d2 = lsum.suggest_dimensions("丸パイプφ42.7")
    assert d2["diameter_mm"] == 42.7
    d3 = lsum.suggest_dimensions("鉄板t9")
    assert d3["thickness_mm"] == 9.0
