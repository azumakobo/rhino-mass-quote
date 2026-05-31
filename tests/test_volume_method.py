"""ポリサーフェス体積→重量(volume_to_weight)を標準とする方針のテスト（2026-05-31）。"""

import os

import pytest

from steel_estimator import layer_summary as lsum
from steel_estimator import layer_estimate as lest
from steel_estimator import layer_mapping as lmap
from steel_estimator.rhino_csv import RhinoObject


def _summary(layer, **kw):
    o = RhinoObject(layer_name=layer, object_count=1, **kw)
    return lsum.build_summary([o])[0]


# ---- suggested_calc_type: 鋼材ポリサーフェス → volume_to_weight ----

@pytest.mark.parametrize("layer", [
    "SQPIPE_STKR_40x40_t2.3", "PIPE_STK_D48.6_t2.3",
    "ANGLE_SS400_40x40_t3", "FB_SS400_50x4.5",
])
def test_steel_solid_is_volume_to_weight(layer):  # 必須1-4
    s = _summary(layer, object_type="Brep", is_closed_brep=True, object_volume_mm3=2_000_000)
    assert s["suggested_calc_type"] == "volume_to_weight"


def test_plate_stays_area_to_weight():  # 必須10
    s = _summary("PL_SS400_t6", object_type="Curve", is_closed_curve=True,
                 object_area_mm2=500_000, object_curve_length_mm=3000)
    assert s["suggested_calc_type"] == "area_to_weight"


def test_steel_without_volume_falls_back_to_curve():  # 必須11(互換)
    s = _summary("SQPIPE_STKR_40x40_t2.3", object_type="Curve", is_curve=True,
                 object_curve_length_mm=6000)
    assert s["suggested_calc_type"] == "curve_length_to_stock"


def test_steel_zero_volume_zero_curve_warns():  # 必須9
    s = _summary("ANGLE_SS400_40x40_t3", object_type="Brep")
    # 体積も曲線も無い → curve/volumeどちらでもないため warning が付く
    assert s["warning"]


# ---- volume_to_weight 計算（密度・kg単価） ----

def _mrow(**kw):
    base = {f: "" for f in lmap.MAPPING_FIELDS}
    base["enabled"] = "true"
    base["waste_rate"] = "1.0"
    base.update(kw)
    return base


def test_volume_to_weight_ss400_density():  # 必須5
    summary = [{"layer_name": "S", "total_volume_mm3": "2000000", "object_count": "1",
                "total_area_m2": "", "total_curve_length_m": ""}]
    mapping = [_mrow(layer_name="S", calc_type="volume_to_weight", material_category="square_pipe",
                     density_g_cm3="7.85", unit_price="260", price_unit="kg")]
    results, _ = lest.estimate_layers(summary, mapping, tax_rate=0.10)
    r = results[0]
    # 2,000,000 mm3 × 7.85 × 1e-6 = 15.7 kg
    assert abs(float(r["estimated_weight_kg"]) - 15.7) < 0.01
    # 15.7 × 260 = 4082
    assert abs(float(r["estimated_amount_ex_tax"]) - 4082) < 1


def test_zero_volume_needs_review():  # 必須9
    summary = [{"layer_name": "S", "total_volume_mm3": "0", "object_count": "1",
                "total_area_m2": "", "total_curve_length_m": ""}]
    mapping = [_mrow(layer_name="S", calc_type="volume_to_weight", material_category="angle",
                     density_g_cm3="7.85", unit_price="300", price_unit="kg")]
    results, _ = lest.estimate_layers(summary, mapping, tax_rate=0.10)
    assert results[0]["needs_review"] == "true"
    assert "体積" in results[0]["warning"]


# ---- 公開参考価格 kg単価との接続（enrich） ----

def _public_ranges():
    from steel_estimator import public_data as pub
    from steel_estimator import csv_utils as cu
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pdir = os.path.join(root, "public_reference_data")
    shape = pub.public_shape_to_range(cu.read_dicts(os.path.join(pdir, "public_shape_reference_prices.csv")))
    plate = pub.public_plate_to_range(cu.read_dicts(os.path.join(pdir, "public_plate_reference_prices.csv")))
    return plate, shape


def test_enrich_uses_public_kg_price_median():  # 必須6,7
    from steel_estimator import enrich
    plate, shape = _public_ranges()
    m = [_mrow(layer_name="SQ", calc_type="volume_to_weight", material_category="square_pipe",
               width_mm="40", height_mm="40", thickness_mm="2.3", price_unit="kg")]
    out = enrich.enrich_mapping(m, [], [], tax_rate=0.10, plate_range_rows=plate, shape_range_rows=shape)
    r = out[0]
    assert r["unit_price"] != ""            # kg単価が補完された
    assert r["price_unit"] == "kg"
    assert r.get("pricing_mode") in ("median", "manual")


# ---- estimate-public-rhino がポリサーフェスデモで通る ----

def test_estimate_public_rhino_solids_demo():  # 必須12,13
    from steel_estimator import public_rhino as pr
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sample = os.path.join(root, "samples", "rhino_objects_demo.csv")
    pdir = os.path.join(root, "public_reference_data")
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        res = pr.estimate_public_rhino(sample, td, tax_rate=0.10, public_dir=pdir)
        what = res["what"]
        steel = [w for w in what if w["calc_type"] == "volume_to_weight"]
        assert len(steel) >= 3                       # 角/丸/FB が体積方式
        for w in steel:
            assert w["estimated_weight_kg"]          # 重量が出る（必須13）
            assert w["price_unit"] == "kg"


def test_curve_methods_still_exist():  # 必須11
    # 中心線方式の calc_type 定数が残っている（互換）
    assert lmap.CALC_CURVE_TO_STOCK == "curve_length_to_stock"
    assert lmap.CALC_CURVE_TO_METER == "curve_length_to_meter"
