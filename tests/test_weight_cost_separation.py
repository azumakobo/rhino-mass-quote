"""重量計算用素材（密度）と 概算用単価カテゴリ（円/kg）の分離のテスト。

Rhino非依存の core ロジックのみ検証（Eto/Rhino部分は除く）。
"""

import importlib.util
import os

import pytest


_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PUBLIC = os.path.join(_ROOT, "public_reference_data")


def _load(name):
    spec = importlib.util.spec_from_file_location(name[:-3], os.path.join(_ROOT, "rhino_scripts", name))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


core = _load("steel_estimate_core_for_rhino.py")
_REF = core.load_reference(_PUBLIC)
_CAT = core.build_price_catalog(_REF)
_V1M3 = 1_000_000_000  # 1 m³ = 1e9 mm³


def _entry(key):
    return core.find_price_entry(_CAT, key)


# ---- 密度（重量計算用素材） ----

def test_density_materials_three_choices():
    """Quote の重量計算用素材は金属3択（内部値 steel/stainless/aluminum）。"""
    keys = [k for k, _ in core.DENSITY_MATERIALS]
    assert keys == ["steel", "stainless", "aluminum"]
    assert core.density_for_material("steel") == 7.85
    assert core.density_for_material("stainless") == 7.93
    assert core.density_for_material("aluminum") == 2.70


def test_grade_to_quote_material_mapping():
    for n in ("SS400", "STK", "STKR", "Steel", "PL_SS400_t6"):
        assert core.map_grade_to_quote_material(n) == "steel"
    for n in ("SUS304", "SUS", "Stainless"):
        assert core.map_grade_to_quote_material(n) == "stainless"
    for n in ("A5052", "Aluminum", "AL"):
        assert core.map_grade_to_quote_material(n) == "aluminum"


# ---- 価格カタログ（公開参考価格CSV由来） ----

def test_price_catalog_built():
    assert len(_CAT) > 50
    assert _entry("PL_SS400_t6") is not None
    assert _entry("PL_SS400_t9") is not None
    assert any(e["category"] == "square_pipe" for e in _CAT)
    assert any(e["category"] == "round_pipe" for e in _CAT)


def test_price_catalog_labels():
    e6 = _entry("PL_SS400_t6")
    assert "板 SS400 t6" in e6["label"]
    assert "270" in e6["label"]      # 元単価270が併記される
    assert "330" in e6["label"]      # 補正後330（270×1.2,10円切上）
    assert "安全係数" in e6["label"]
    # ラベルに種別名の重複がない（角パイプ 角パイプ … にならない）
    sq = [e for e in _CAT if e["category"] == "square_pipe"][0]
    assert sq["label"].count("角パイプ") == 1


# ---- 確認テスト 1〜3（1m³ Box） ----

def test_scenario1_steel_pl_t6():
    # 安全係数1.2+10円切上: 270→330。7850kg×330=2,590,500
    up, _ = core.resolve_unit_price(_entry("PL_SS400_t6"), "recommended")
    assert up == 330
    w, cost, _ = core.compute_cost(_V1M3, core.density_for_material("steel"), up)
    assert w == pytest.approx(7850.0, abs=0.5)
    assert round(cost) == 2_590_500


def test_scenario2_steel_pl_t9():
    # 260→312→10円切上320。7850kg×320=2,512,000
    up, _ = core.resolve_unit_price(_entry("PL_SS400_t9"), "recommended")
    assert up == 320
    w, cost, _ = core.compute_cost(_V1M3, core.density_for_material("steel"), up)
    assert w == pytest.approx(7850.0, abs=0.5)
    assert round(cost) == 2_512_000


def test_scenario3_sus304_manual_800():
    # manual は安全係数を掛けない → 800 のまま。7930kg×800=6,344,000
    up, _ = core.resolve_unit_price(_entry("PL_SS400_t6"), "manual", 800)
    assert up == 800
    w, cost, _ = core.compute_cost(_V1M3, core.density_for_material("stainless"), up)
    assert w == pytest.approx(7930.0, abs=0.5)
    assert round(cost) == 6_344_000


def test_density_independent_of_price_category():
    """密度用素材は同じでも、価格カテゴリ変更で金額だけ変わる（重量は不変）。"""
    dens = core.density_for_material("steel")
    up6, _ = core.resolve_unit_price(_entry("PL_SS400_t6"), "recommended")
    up9, _ = core.resolve_unit_price(_entry("PL_SS400_t9"), "recommended")
    w6, c6, _ = core.compute_cost(_V1M3, dens, up6)
    w9, c9, _ = core.compute_cost(_V1M3, dens, up9)
    assert w6 == w9                  # 重量は密度で決まり不変
    assert c6 != c9                  # 金額は単価カテゴリで変わる


def test_conservative_mode():
    e = _entry("PL_SS400_t6")
    up_rec, _ = core.resolve_unit_price(e, "recommended")
    up_con, _ = core.resolve_unit_price(e, "conservative")
    assert up_con >= up_rec          # conservative は recommended 以上


def test_angle_no_kg_price_needs_manual():
    ea = [e for e in _CAT if e["category"] == "angle"][0]
    up, warn = core.resolve_unit_price(ea, "recommended")
    assert up is None and warn       # kg単価なし → manual を促す


# ---- 設定の保存/読込（前回値を保持しつつ変更可能） ----

def test_settings_roundtrip(tmp_path):
    p = str(tmp_path / "weight_calc_settings.json")
    core.save_settings({
        "last_density_material": "SUS304", "last_density_value": 7.93,
        "last_price_category": "PL_SS400_t9", "last_pricing_mode": "manual",
        "manual_unit_prices_by_category": {"PL_SS400_t6": 800},
    }, path=p, now_str="2026-05-31 12:00:00")
    s = core.load_settings(p)
    assert s["last_density_material"] == "SUS304"
    assert s["last_price_category"] == "PL_SS400_t9"
    assert s["last_pricing_mode"] == "manual"
    assert s["manual_unit_prices_by_category"]["PL_SS400_t6"] == 800
    assert s["last_updated"] == "2026-05-31 12:00:00"


def test_settings_missing_returns_empty(tmp_path):
    assert core.load_settings(str(tmp_path / "none.json")) == {}


# ---- Rhinoスクリプト本体は通常Pythonでimport可・main()は友好エラー ----

def test_weight_cost_script_friendly_error():
    panel = _load("weight_cost_estimate_rhino.py")
    assert panel.running_in_rhino() is False
    with pytest.raises(RuntimeError) as ei:
        panel.main()
    assert "Rhino" in str(ei.value)


# ---- 安全係数 1.2（Quote公開参考価格のみ・manual除外） ----

def test_quote_safety_factor_constant():
    assert core.QUOTE_PRICE_FACTOR == 1.2


def test_safety_factor_ceil10_examples():
    # apply_quote_factor: ×1.2 → 10円切上
    assert core.apply_quote_factor(270) == 330   # 324→330
    assert core.apply_quote_factor(280) == 340   # 336→340
    assert core.apply_quote_factor(260) == 320   # 312→320
    assert core.apply_quote_factor(290) == 350   # 348→350
    assert core.apply_quote_factor(210) == 260   # 252→260
    assert core.apply_quote_factor(None) is None


def test_representative_categories_factored():
    # 既知アンカー（公開データの実値）: 板 t6=270→330, t9=260→320
    assert core.resolve_unit_price(_entry("PL_SS400_t6"), "recommended")[0] == 330
    assert core.resolve_unit_price(_entry("PL_SS400_t9"), "recommended")[0] == 320
    # 各カテゴリの実カタログ先頭エントリで resolve == raw×1.2(10円切上) を検証（係数が効いている）
    for cat in ("plate", "square_pipe", "round_pipe", "flat_bar"):
        e = next((x for x in _CAT if x["category"] == cat
                  and x["recommended_per_kg"] is not None), None)
        assert e is not None, cat
        up, _ = core.resolve_unit_price(e, "recommended")
        assert up == core.apply_quote_factor(e["recommended_per_kg"]), (cat, e["key"], up)


def test_manual_not_factored():
    up, _ = core.resolve_unit_price(_entry("PL_SS400_t6"), "manual", 800)
    assert up == 800                      # 手入力は1.2倍しない
    up2, _ = core.resolve_unit_price(_entry("PL_SS400_t6"), "manual", 1000)
    assert up2 == 1000


def test_csv_values_unchanged_by_factor():
    """安全係数は計算時のみ。recommended(中央値)はそのまま、conservativeは安全側clamp済値。"""
    e = _entry("PL_SS400_t6")
    assert e["recommended_per_kg"] == 270.0
    # 安全側は中央値270の1.3倍以上にclamp（元max280<351のため引上げ→公開で10円切上=360）
    assert e["conservative_per_kg"] == 360.0
    assert e["conservative_per_kg"] >= 270.0 * 1.3
    # 補正後（×1.2,10円切上）はquoted列に保持
    assert e["recommended_per_kg_quoted"] == 330      # 270×1.2→330
    assert e["conservative_per_kg_quoted"] == 440      # 360×1.2=432→440


def test_custom_factor_param():
    assert core.apply_quote_factor(100, factor=1.0) == 100
    up, _ = core.resolve_unit_price(_entry("PL_SS400_t6"), "recommended", factor=1.0)
    assert up == 270    # 係数1.0なら元のまま（270→ceil10→270）
