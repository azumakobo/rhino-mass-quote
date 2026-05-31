# -*- coding: utf-8 -*-
"""Mass（重量計算）用の軽量ロジック（Rhino非依存・標準ライブラリのみ）。

v1相当の「素材密度ベースの重量計算」ツール。金属だけでなく木材・合板・MDF・
アクリル・樹脂なども扱う。必要なら簡単な材料費（¥/kg）も出せる。
※ 概算見積（価格カテゴリ選択）は Quote 側（steel_estimate_core_for_rhino）に分離。

内部キーは英語、UI表示は日本語（label）。
"""

import json as _json
import os
import io

# (内部キー, 日本語表示, 既定密度 g/cm3)。Custom は密度を手入力。
MASS_MATERIALS = [
    ("steel", "鉄", 7.85),
    ("stainless", "ステンレス", 7.93),
    ("aluminum", "アルミ", 2.70),
    ("wood", "木材", 0.50),
    ("plywood", "合板", 0.55),
    ("mdf", "MDF", 0.75),
    ("acrylic", "アクリル", 1.19),
    ("resin", "樹脂", 1.20),
    ("custom", "カスタム", None),
]
MASS_LABEL = {k: lbl for k, lbl, _ in MASS_MATERIALS}
MASS_DENSITY = {k: d for k, _, d in MASS_MATERIALS}


def material_label(key):
    return MASS_LABEL.get(key, key)


def density_for(material, custom_value=None):
    """素材キーから密度 g/cm3。custom は custom_value。"""
    if material == "custom":
        return _f(custom_value)
    return MASS_DENSITY.get(material)


def _f(v):
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def compute_mass(volume_mm3, density_g_cm3, unit_price_per_kg=None):
    """(weight_kg, volume_m3, cost_jpy)。cost は unit_price がある時のみ。

    weight_kg = volume_mm3 × density_g_cm3 × 1e-6（= v1のmass計算）。
    """
    vol = _f(volume_mm3) or 0.0
    dens = _f(density_g_cm3)
    volume_m3 = vol / 1000000000.0
    weight = vol * dens * 1e-6 if dens is not None else None
    up = _f(unit_price_per_kg)
    cost = weight * up if (weight is not None and up is not None) else None
    return weight, volume_m3, cost


# ---- 設定（Quoteとは別ファイル） ----

def settings_path():
    return os.path.join(os.path.expanduser("~"), "Documents", "RhinoScripts",
                        "mass_settings.json")


def load_settings(path=None):
    path = path or settings_path()
    if not os.path.exists(path):
        return {}
    try:
        with io.open(path, encoding="utf-8") as f:
            return _json.load(f)
    except Exception:
        return {}


def save_settings(data, path=None, now_str=None):
    path = path or settings_path()
    folder = os.path.dirname(os.path.abspath(path))
    if folder and not os.path.isdir(folder):
        os.makedirs(folder, exist_ok=True)
    out = dict(data)
    if now_str is not None:
        out["last_updated"] = now_str
    with io.open(path, "w", encoding="utf-8") as f:
        _json.dump(out, f, ensure_ascii=False, indent=2)
    return path
