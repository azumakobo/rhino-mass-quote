"""Quote 実機バグ修正の検証: 無言終了させない・label変換・None安全整形・例外表示。"""

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


q = _load("quote_estimate_rhino.py")
core = _load("steel_estimate_core_for_rhino.py")
_CAT = core.build_price_catalog(core.load_reference(_PUBLIC))


def _entry(key):
    return core.find_price_entry(_CAT, key)


# ---- pricing_mode 日本語ラベル → 内部値 ----

def test_pricing_mode_label_to_internal():
    modes = ["recommended", "conservative", "manual"]
    labels = [core.pricing_mode_label(m) for m in modes]
    assert q._label_to_value("通常見積（中央値）", labels, modes, "recommended") == "recommended"
    assert q._label_to_value("安全側見積（最大値）", labels, modes, "recommended") == "conservative"
    assert q._label_to_value("手入力", labels, modes, "recommended") == "manual"


def test_label_to_value_fallback_no_crash():
    modes = ["recommended", "conservative", "manual"]
    labels = [core.pricing_mode_label(m) for m in modes]
    # 一致しないラベルでも例外を出さず既定値を返す（.index ValueErrorを防ぐ）
    assert q._label_to_value("謎ラベル", labels, modes, "recommended") == "recommended"
    assert q._label_to_value(None, labels, modes, "manual") == "manual"
    # 前後空白の揺れも吸収
    assert q._label_to_value(" 手入力 ", labels, modes, "recommended") == "manual"


def test_material_label_to_internal():
    keys = [k for k, _ in core.DENSITY_MATERIALS]
    labels = [core.material_label(k) for k in keys]
    assert q._label_to_value(core.material_label("steel"), labels, keys, "steel") == "steel"
    assert q._label_to_value(core.material_label("stainless"), labels, keys, "steel") == "stainless"


# ---- unit_price が各modeで取れる ----

def test_unit_price_recommended():
    up, w = core.resolve_unit_price(_entry("PL_SS400_t6"), "recommended")
    assert up == 330 and w == ""              # 270×1.2→330


def test_unit_price_conservative():
    up, _ = core.resolve_unit_price(_entry("PL_SS400_t6"), "conservative")
    # t6 安全側= clamp後360 ×1.2 →432→10円切上440
    assert up == 440


def test_unit_price_manual():
    up, _ = core.resolve_unit_price(_entry("PL_SS400_t6"), "manual", 800)
    assert up == 800                          # 手入力は係数なし


def test_unit_price_none_does_not_crash():
    # angle等kg単価なし → None + warning（無言終了でなくwarningを返す）
    ea = [e for e in _CAT if e["category"] == "angle"][0]
    up, warn = core.resolve_unit_price(ea, "recommended")
    assert up is None and warn


# ---- 結果整形が None を含んでも落ちない ----

def test_fmt_yen_none_safe():
    assert q._fmt_yen(None) == "—"
    assert q._fmt_yen("") == "—"
    assert q._fmt_yen(2119500) == "2,119,500 円"
    assert q._fmt_yen(330.0) == "330 円"


def test_fmt_kg_none_safe():
    assert q._fmt_kg(None) == "0"
    assert q._fmt_kg(7850.0) == "7850"
    assert q._fmt_kg(0) == "0"


# ---- 1m³ Box の3ケース（compute_cost まで通る） ----

_V1M3 = 1000000000


def test_caseA_steel_t6_recommended():
    up, _ = core.resolve_unit_price(_entry("PL_SS400_t6"), "recommended")
    w, cost, _ = core.compute_cost(_V1M3, core.density_for_material("steel"), up)
    assert w == pytest.approx(7850.0, abs=0.5)
    assert q._fmt_yen(cost) == "2,590,500 円"   # 7850×330


def test_caseB_steel_t6_conservative():
    up, _ = core.resolve_unit_price(_entry("PL_SS400_t6"), "conservative")
    w, cost, _ = core.compute_cost(_V1M3, core.density_for_material("steel"), up)
    assert w == pytest.approx(7850.0, abs=0.5)
    assert round(cost) == 7850 * 440            # 安全側440


def test_caseC_manual_800_no_factor():
    up, _ = core.resolve_unit_price(_entry("PL_SS400_t6"), "manual", 800)
    w, cost, _ = core.compute_cost(_V1M3, core.density_for_material("steel"), up)
    assert up == 800
    assert round(cost) == 7850 * 800


# ---- 例外は無言で潰さない（Rhino外でも友好エラー） ----

def test_main_outside_rhino_raises_runtime():
    assert q.running_in_rhino() is False
    with pytest.raises(RuntimeError):
        q.main()


def test_debug_version_banner():
    assert q.QUOTE_VERSION == "quote-debug-2026-05-31"


# ---- 依存core同期・バージョン・古いキャッシュ対策 ----

def test_core_has_version_and_factor():
    assert core.QUOTE_PRICE_FACTOR == 1.2
    assert core.CORE_VERSION == "steel-estimate-core-quote-factor-2026-05-31"


def test_load_core_returns_current_core():
    c = q._load_core()
    assert getattr(c, "QUOTE_PRICE_FACTOR", None) == 1.2
    assert getattr(c, "CORE_VERSION", None)


def test_load_core_force_reload_replaces_stale_cache():
    import sys
    class _Stale:
        pass
    sys.modules["steel_estimate_core_for_rhino"] = _Stale()   # 古いキャッシュを偽装
    c = q._load_core()                                         # 強制リロードされるはず
    assert getattr(c, "QUOTE_PRICE_FACTOR", None) == 1.2


def test_rhinoscripts_core_synced():
    rs_core = os.path.join(os.path.expanduser("~"), "Documents", "RhinoScripts",
                           "steel_estimate_core_for_rhino.py")
    assert os.path.exists(rs_core)
    src = open(rs_core, encoding="utf-8").read()
    assert "QUOTE_PRICE_FACTOR = 1.2" in src
    assert "CORE_VERSION" in src
