"""Mass（重量計算）と Quote（概算見積）の分離・日本語化のテスト。"""

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


mass = _load("mass_core_for_rhino.py")
core = _load("steel_estimate_core_for_rhino.py")


# ===== Mass（v1相当・木材など金属以外も） =====

def test_mass_materials_include_wood_and_metals():
    keys = [k for k, _, _ in mass.MASS_MATERIALS]
    for k in ("steel", "stainless", "aluminum", "wood", "plywood", "mdf", "acrylic", "resin", "custom"):
        assert k in keys


def test_mass_labels_japanese():
    assert mass.material_label("steel") == "鉄"
    assert mass.material_label("wood") == "木材"
    assert mass.material_label("plywood") == "合板"
    assert mass.material_label("acrylic") == "アクリル"


def test_mass_density_and_weight():
    assert mass.density_for("steel") == 7.85
    assert mass.density_for("wood") == 0.50
    assert mass.density_for("custom", 1.23) == 1.23
    # 1m³ の鉄 → 7850kg
    w, vm, cost = mass.compute_mass(1_000_000_000, 7.85)
    assert w == pytest.approx(7850.0, abs=0.5)
    assert vm == pytest.approx(1.0, abs=1e-9)
    assert cost is None                      # 単価未指定なら金額なし
    # 木材 1m³ → 500kg、単価あり→金額
    w2, _, cost2 = mass.compute_mass(1_000_000_000, 0.50, 300)
    assert w2 == pytest.approx(500.0, abs=0.5)
    assert round(cost2) == 150000


def test_mass_settings_separate_file(tmp_path):
    p = str(tmp_path / "mass_settings.json")
    mass.save_settings({"last_material": "wood", "density_by_material": {"wood": 0.5},
                        "unit_price_by_material": {"wood": 300}}, path=p, now_str="2026-05-31")
    s = mass.load_settings(p)
    assert s["last_material"] == "wood"
    assert "mass_settings" in mass.settings_path()


def test_mass_script_friendly_error():
    m = _load("mass_rhino.py")
    assert m.running_in_rhino() is False
    with pytest.raises(RuntimeError) as ei:
        m.main()
    assert "Rhino" in str(ei.value)


def _read_script(name):
    with open(os.path.join(_ROOT, "rhino_scripts", name), encoding="utf-8") as f:
        return f.read()


def test_mass_no_usertext_no_csv():
    """Mass標準フローは UserText書き込み も CSV保存 も行わない（確認ダイアログ無し）。"""
    src = _read_script("mass_rhino.py")
    assert "SetUserString" not in src          # UserText自動書き込みなし
    assert "rwc_" not in src                   # rwc_* も書かない
    assert "write_csv" not in src and "steel_estimate_result" not in src  # CSV保存なし
    # 確認ダイアログ的な分岐（保存しますか？）が無い
    assert "保存しますか" not in src and "書き込みますか" not in src


def test_quote_still_writes_usertext():
    """Quote側は従来どおり UserText(quote_*) を書く（Massの変更は波及しない）。"""
    src = _read_script("quote_estimate_rhino.py")
    assert "quote_density_material" in src
    assert "SetUserString" in src


# ===== Quote（日本語UI・内部値は英語維持） =====

def test_quote_material_three_choices_japanese():
    """Quoteの重量計算用素材は金属3択・日本語表示。"""
    keys = [k for k, _ in core.DENSITY_MATERIALS]
    assert keys == ["steel", "stainless", "aluminum"]
    assert core.material_label("steel") == "鉄（SS400 / STK / STKR）"
    assert core.material_label("stainless") == "ステンレス（SUS304）"
    assert core.material_label("aluminum") == "アルミ（A5052）"
    # 木材等は Quote の素材選択肢に出ない（Mass専用）
    assert "wood" not in keys and "custom" not in keys


def test_quote_pricing_mode_labels_japanese():
    assert core.pricing_mode_label("recommended") == "通常見積（中央値）"
    assert core.pricing_mode_label("conservative") == "安全側見積（最大値）"
    assert core.pricing_mode_label("manual") == "手入力"


def test_quote_internal_values_preserved():
    # 内部値はそのまま（CSVキー・設定値は英語）
    cat = core.build_price_catalog(core.load_reference(_PUBLIC))
    e = core.find_price_entry(cat, "PL_SS400_t6")
    assert e is not None
    # 元データ(entry)は無補正で保持。resolve_unit_priceは安全係数1.2+10円切上を適用。
    assert e["recommended_per_kg"] == 270.0    # 元CSV値はそのまま
    up, _ = core.resolve_unit_price(e, "recommended")
    assert up == 330                            # 270×1.2=324→10円切上330
    up2, _ = core.resolve_unit_price(e, "conservative")
    assert up2 >= up


def test_quote_catalog_labels_japanese_no_english_mode():
    cat = core.build_price_catalog(core.load_reference(_PUBLIC))
    e = core.find_price_entry(cat, "PL_SS400_t6")
    assert "通常" in e["label"] and "安全側" in e["label"]
    assert "recommended" not in e["label"] and "conservative" not in e["label"]


def test_quote_settings_separate_from_mass():
    assert "quote_settings" in core.quote_settings_path()
    assert "mass_settings" in core.mass_settings_path()
    assert core.quote_settings_path() != core.mass_settings_path()


def test_quote_script_and_shim_friendly_error():
    q = _load("quote_estimate_rhino.py")
    assert q.running_in_rhino() is False
    with pytest.raises(RuntimeError):
        q.main()
    # 旧名シムも新ファイルを呼ぶだけ
    shim = _load("weight_cost_estimate_rhino.py")
    assert shim.running_in_rhino() is False
    with pytest.raises(RuntimeError):
        shim.main()


# ===== Rhinoコマンド配置（RhinoScripts側）の検査 =====

_RHINO_SCRIPTS = os.path.join(os.path.expanduser("~"), "Documents", "RhinoScripts")


def test_rhinoscripts_deployment_exists():
    """Quote/Mass と依存coreが RhinoScripts に配置されている。"""
    for f in ("quote_estimate_rhino.py", "mass_rhino.py",
              "steel_estimate_core_for_rhino.py", "mass_core_for_rhino.py"):
        assert os.path.exists(os.path.join(_RHINO_SCRIPTS, f)), f


def test_version_banners_present():
    q = open(os.path.join(_ROOT, "rhino_scripts", "quote_estimate_rhino.py"), encoding="utf-8").read()
    m = open(os.path.join(_ROOT, "rhino_scripts", "mass_rhino.py"), encoding="utf-8").read()
    assert "quote-debug-2026-05-31" in q and "----- Quote script -----" in q
    assert "mass-2026-05-31" in m and "----- Mass script -----" in m


def test_command_registration_doc_has_macros():
    doc = open(os.path.join(_ROOT, "docs", "rhino-command-registration.md"), encoding="utf-8").read()
    assert '_-RunPythonScript "/Users/<you>/Documents/RhinoScripts/quote_estimate_rhino.py"' in doc
    assert '_-RunPythonScript "/Users/<you>/Documents/RhinoScripts/mass_rhino.py"' in doc
