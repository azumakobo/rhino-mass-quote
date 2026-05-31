"""Rhino内UIの軽量ロジック（steel_estimate_core_for_rhino）のテスト（Phase RC4）。

Eto/RhinoCommon部分は pytest で検証できないため、Rhino非依存のコアロジックを検証する。
"""

import importlib.util
import math
import os

import pytest


_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPTS = os.path.join(_ROOT, "rhino_scripts")
_PUBLIC = os.path.join(_ROOT, "public_reference_data")


def _load(name):
    spec = importlib.util.spec_from_file_location(name[:-3], os.path.join(_SCRIPTS, name))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


core = _load("steel_estimate_core_for_rhino.py")


def _ref():
    return core.load_reference(_PUBLIC)


def test_load_reference():  # 必須1
    ref = _ref()
    assert len(ref["plate"]) > 0 and len(ref["shape"]) > 0


@pytest.mark.parametrize("name,expected", [
    ("PL_SS400_t6", "plate"),
    ("SQPIPE_STKR_40x40_t2.3", "square_pipe"),
    ("PIPE_STK_D48.6_t2.3", "round_pipe"),
    ("ANGLE_SS400_40x40_t3", "angle"),
    ("FB_SS400_50x4.5", "flat_bar"),
    ("BOLT_TEST", "object_count"),
    ("IGNORE_GUIDE", "ignore"),
])
def test_infer_category(name, expected):  # 必須2
    assert core.infer_category(name) == expected


def test_volume_weight_calc():  # 必須3,4,5,6
    vol = 2_000_000.0
    w = core.weight_from_volume(vol, 7.85)
    assert abs(w - 15.7) < 0.01


def _est(name, **agg):
    agg.setdefault("layer_name", name)
    return core.estimate_layer(agg, _ref(), 0.10, "median")


def test_sqpipe_volume_to_weight():  # 必須3,7,8
    vol = (40 * 40 - (40 - 2 * 2.3) ** 2) * 6000
    r = _est("SQPIPE_STKR_40x40_t2.3", volume_mm3=vol)
    assert r["calc_type"] == "volume_to_weight"
    assert float(r["weight_kg"]) > 0
    assert float(r["unit_price_ex_tax"]) > 0       # kg単価が引けた
    assert float(r["amount_ex_tax"]) > 0           # 金額が出る
    assert float(r["amount_inc_tax"]) > float(r["amount_ex_tax"])  # 税込>税抜


def test_pipe_volume_to_weight():  # 必須4
    vol = (math.pi / 4 * (48.6 ** 2 - (48.6 - 4.6) ** 2)) * 6000
    r = _est("PIPE_STK_D48.6_t2.3", volume_mm3=vol)
    assert r["calc_type"] == "volume_to_weight"
    assert float(r["amount_ex_tax"]) > 0


def test_fb_volume_to_weight():  # 必須6
    r = _est("FB_SS400_50x4.5", volume_mm3=50 * 4.5 * 3000)
    assert r["calc_type"] == "volume_to_weight"
    assert float(r["amount_ex_tax"]) > 0


def test_angle_weight_but_no_kg_price():  # 必須5（重量は出る/kg単価無で要確認）
    r = _est("ANGLE_SS400_40x40_t3", volume_mm3=(40 + 40 - 3) * 3 * 3000)
    assert r["calc_type"] == "volume_to_weight"
    assert float(r["weight_kg"]) > 0
    assert r["amount_ex_tax"] == ""                # kg単価なし→金額未確定
    assert "kg単価" in r["warning"]


def test_plate_area_to_weight():
    r = _est("PL_SS400_t6", area_m2=0.5)
    assert r["calc_type"] == "area_to_weight"
    assert float(r["weight_kg"]) > 0
    assert float(r["amount_ex_tax"]) > 0


def test_density_for_grade():
    assert core.density_for_grade("SS400")[0] == 7.85
    assert core.density_for_grade("SUS304")[0] == 7.93
    assert core.density_for_grade("A5052")[0] == 2.70
    d, warn = core.density_for_grade("UNKNOWN")
    assert d == 7.85 and warn


def test_estimate_all_and_totals():  # 必須7,8
    aggs = [
        {"layer_name": "PL_SS400_t6", "area_m2": 0.5},
        {"layer_name": "SQPIPE_STKR_40x40_t2.3", "volume_mm3": 2_000_000},
        {"layer_name": "IGNORE_GUIDE"},
    ]
    rows, totals = core.estimate_all(aggs, _ref(), 0.10, "median")
    assert len(rows) == 3
    assert totals["subtotal_ex_tax"] > 0
    assert totals["subtotal_inc_tax"] == totals["subtotal_ex_tax"] + totals["tax_amount"]
    assert "recommended_ex_tax" in totals and "conservative_ex_tax" in totals


def test_csv_rows_and_bom(tmp_path):  # 必須9
    aggs = [{"layer_name": "SQPIPE_STKR_40x40_t2.3", "volume_mm3": 2_000_000}]
    rows, _ = core.estimate_all(aggs, _ref(), 0.10, "median")
    p = tmp_path / "steel_estimate_result.csv"
    core.write_csv(str(p), rows)
    with open(p, "rb") as f:
        assert f.read(3) == b"\xef\xbb\xbf"
    # ヘッダー列が規定どおり
    import csv as _csv
    with open(p, encoding="utf-8-sig") as f:
        header = next(_csv.reader(f))
    assert header == core.CSV_COLUMNS


def test_panel_import_and_friendly_error():  # 必須10
    panel = _load("steel_estimate_rhino_panel.py")  # import時に落ちない
    assert panel.running_in_rhino() is False
    with pytest.raises(RuntimeError) as ei:
        panel.main()
    assert "Rhino" in str(ei.value)


def test_resolve_output_path_desktop():
    p = core.resolve_output_path(None)
    assert p.endswith("steel_estimate_result.csv")


# ===== 簡素化方針(2026-05-31): volume優先・断面再現なし・カテゴリfallback =====

@pytest.mark.parametrize("name", [
    "SQPIPE_STKR_40x40_t2.3", "PIPE_STK_D48.6_t2.3",
    "ANGLE_SS400_40x40_t3", "FB_SS400_50x4.5",
])
def test_plain_box_volume_is_volume_to_weight(name):
    """ただのBox体積でも（断面再現せず）volume_to_weight になる。"""
    r = _est(name, volume_mm3=4_800_000)   # 形状無関係のBox体積
    assert r["calc_type"] == "volume_to_weight"
    assert float(r["weight_kg"]) > 0


def test_plate_with_volume_is_volume_to_weight():
    """PLでもvolumeがあれば volume_to_weight（area_to_weightはfallback）。"""
    r = _est("PL_SS400_t6", volume_mm3=3_000_000)
    assert r["calc_type"] == "volume_to_weight"
    assert float(r["amount_ex_tax"]) > 0


def test_plate_volume_takes_priority_over_area():
    r = _est("PL_SS400_t6", volume_mm3=3_000_000, area_m2=0.5)
    assert r["calc_type"] == "volume_to_weight"   # volume優先


def test_category_fallback_price_with_warning():
    """寸法が公開参考に無いSQPIPEでも、同カテゴリ代表kg単価で金額が出る（warning付き）。"""
    r = _est("SQPIPE_STKR_999x999_t9.9", volume_mm3=5_000_000)
    assert r["calc_type"] == "volume_to_weight"
    assert float(r["unit_price_ex_tax"]) > 0       # fallback単価で金額が出る
    assert float(r["amount_ex_tax"]) > 0
    assert "fallback" in r["warning"]


def test_no_volume_no_area_needs_review():
    r = _est("STEEL_PART_UNKNOWN")  # volume/areaなし
    assert r["calc_type"] == "needs_review"


def test_unknown_grade_density_warning():
    r = _est("MYSTERY_BOX", volume_mm3=1_000_000)
    assert r["calc_type"] == "volume_to_weight"
    assert float(r["weight_kg"]) == pytest.approx(7.85, abs=0.01)  # 7.85仮定
    assert "密度7.85" in r["warning"] or "材質不明" in r["warning"]


# ===== 実運用レイヤー名のBox volume から金額が出ることを確認 =====

@pytest.mark.parametrize("layer,volume,expected_unit", [
    ("PL_SS400_t6", 1000 * 500 * 6, 270.0),       # 板 t6
    ("PL_SS400_t9", 1000 * 500 * 9, 260.0),       # 板 t9（厚みで単価が変わる）
    ("SQPIPE_STKR_40x40_t2.3", 40 * 40 * 6000, 260.0),
    ("PIPE_STK_D48.6_t2.3", 48.6 * 48.6 * 6000, 290.0),
    ("FB_SS400_50x4.5", 50 * 4.5 * 3000, 210.0),
])
def test_practical_layer_box_priced(layer, volume, expected_unit):
    """実運用レイヤー名のBox体積から、volume_to_weightで金額が出る。"""
    r = _est(layer, volume_mm3=volume)
    assert r["calc_type"] == "volume_to_weight"
    assert float(r["weight_kg"]) > 0
    assert float(r["unit_price_ex_tax"]) == pytest.approx(expected_unit, abs=0.5)
    assert float(r["amount_ex_tax"]) > 0
    assert float(r["amount_inc_tax"]) > float(r["amount_ex_tax"])


def test_angle_box_warns_no_kg_price():
    r = _est("ANGLE_SS400_40x40_t3", volume_mm3=40 * 40 * 3000)
    assert r["calc_type"] == "volume_to_weight"
    assert float(r["weight_kg"]) > 0
    assert r["amount_ex_tax"] == ""           # kg単価が無い → 金額未確定
    assert "kg単価" in r["warning"]


def test_ignore_layer():
    r = _est("IGNORE_GUIDE")
    assert r["calc_type"] == "ignore"


def test_demo_layers_are_practical_boxes():
    """デモは実運用レイヤー名の単純Box（box/points/guideのみ）。"""
    demo = _load("create_demo_rhino_model.py")
    kinds = {k for _, k, _ in demo.DEMO_LAYERS}
    assert kinds <= {"box", "cylinder", "points", "guide"}
    names = [n for n, _, _ in demo.DEMO_LAYERS]
    for req in ("PL_SS400_t6", "PL_SS400_t9", "SQPIPE_STKR_40x40_t2.3",
                "PIPE_STK_D48.6_t2.3", "FB_SS400_50x4.5", "ANGLE_SS400_40x40_t3",
                "BOLT_TEST", "IGNORE_GUIDE"):
        assert req in names


def test_layer_aggregate_fields_present():
    r = _est("SQPIPE_STKR_40x40_t2.3", volume_mm3=9_600_000, object_count=2)
    for k in ("object_count", "material_grade", "density_g_cm3", "volume_mm3",
              "weight_kg", "unit_price_ex_tax", "amount_ex_tax", "amount_inc_tax", "warning"):
        assert k in r
    assert r["object_count"] == 2
