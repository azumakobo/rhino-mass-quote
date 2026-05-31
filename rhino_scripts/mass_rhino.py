#! python 3
# -*- coding: utf-8 -*-
"""Rhino 8 ScriptEditor / Python 3 / RhinoCommon 専用: Mass（重量計算）。

将来のRhinoコマンド: Mass / _Mass。
選択オブジェクトの体積を取得し、素材密度から重量を出す（v1相当）。
木材・合板・MDF・アクリル・樹脂など金属以外も扱う。必要なら簡単な材料費も出す。
※ 概算見積（公開参考価格の細かい単価カテゴリ）は Quote（quote_estimate_rhino.py）へ分離。

標準フロー: 選択 → 素材選択 →（必要なら）kg単価入力 → 重量・概算材料費を表示 → 終了。
**オブジェクトUserTextへの書き込み・CSV保存は行いません**（確認ダイアログを毎回出さない）。
前回値は設定ファイル ~/Documents/RhinoScripts/mass_settings.json に覚えるだけ。
UI表示はすべて日本語。内部キー・設定JSONキーは英語。
"""

import os
import sys

RHINO_HINT = ("このスクリプトは Rhino 8 の ScriptEditor (Python 3 / RhinoCommon) 専用です。\n"
              "_ScriptEditor で言語を 'Python 3 (CPython / RhinoCommon)' にして実行してください。")


MASS_VERSION = "mass-2026-05-31"


def running_in_rhino():
    try:
        import Rhino  # noqa: F401
        import scriptcontext  # noqa: F401
        return True
    except Exception:
        return False


def _print_banner():
    """実行ファイルの取り違え防止: 実際に動いているファイルパスとバージョンを出す。"""
    try:
        path = os.path.abspath(__file__)
    except Exception:
        path = "(path unknown / RunPythonScript)"
    print("----- Mass script -----")
    print("path: %s" % path)
    print("version: %s" % MASS_VERSION)


def _require_rhino():
    if not running_in_rhino():
        raise RuntimeError(RHINO_HINT)


def _load_core():
    try:
        here = os.path.dirname(os.path.abspath(__file__))
    except Exception:
        here = os.getcwd()
    if here not in sys.path:
        sys.path.insert(0, here)
    # Rhinoセッションのキャッシュで古いcoreが残る対策（最新ファイルから読み直す）
    sys.modules.pop("mass_core_for_rhino", None)
    import mass_core_for_rhino as mass
    return mass


def _unit_scale(doc):
    name = str(getattr(doc, "ModelUnitSystem", "Millimeters"))
    scale = {"Millimeters": 1.0, "Centimeters": 10.0, "Meters": 1000.0,
             "Inches": 25.4, "Feet": 304.8}.get(name, 1.0)
    label = {"Millimeters": "mm", "Centimeters": "cm", "Meters": "m",
             "Inches": "inch", "Feet": "feet"}.get(name, name)
    return scale, label


def _sum_volume_mm3(doc, Rhino, obj_ids):
    """体積合計(mm³), 入力数, 体積計算できたジオメトリ数, 失敗数。"""
    G = Rhino.Geometry
    scale3 = _unit_scale(doc)[0] ** 3
    total, n_in, n_vol, n_fail = 0.0, 0, 0, 0
    for oid in obj_ids:
        obj = doc.Objects.FindId(oid)
        if obj is None:
            continue
        n_in += 1
        geom = obj.Geometry
        brep = geom.ToBrep(True) if isinstance(geom, G.Extrusion) else (
            geom if isinstance(geom, G.Brep) else None)
        try:
            if brep is not None and brep.IsSolid:
                vmp = G.VolumeMassProperties.Compute(brep)
                if vmp:
                    total += float(vmp.Volume) * scale3
                    n_vol += 1
                    continue
            elif isinstance(geom, G.Mesh) and geom.IsClosed:
                vmp = G.VolumeMassProperties.Compute(geom)
                if vmp:
                    total += float(vmp.Volume) * scale3
                    n_vol += 1
                    continue
            n_fail += 1
        except Exception:
            n_fail += 1
    return total, n_in, n_vol, n_fail


def main():
    _print_banner()
    _require_rhino()
    import Rhino
    import scriptcontext as sc
    import rhinoscriptsyntax as rs
    from datetime import datetime

    mass = _load_core()
    doc = sc.doc
    settings = mass.load_settings()

    ids = rs.GetObjects("重量を計算するオブジェクトを選択（未選択でEnterなら全件）",
                        preselect=True, select=False)
    if not ids:
        ids = [o.Id for o in doc.Objects]
    vol_mm3, n_in, n_vol, n_fail = _sum_volume_mm3(doc, Rhino, ids)
    scale, unit_label = _unit_scale(doc)

    # 使用素材を選ぶ（日本語表示・前回値を初期表示）
    keys = [k for k, _, _ in mass.MASS_MATERIALS]
    labels = [mass.material_label(k) for k in keys]
    last = settings.get("last_material", "steel")
    default_label = mass.material_label(last if last in keys else "steel")
    chosen_label = rs.ListBox(labels, "体積から重量を計算する素材を選びます。", "使用素材を選択",
                              default_label)
    if chosen_label is None:
        return
    material = keys[labels.index(chosen_label)]
    density = mass.density_for(material)
    dens_by = settings.get("density_by_material", {}) or {}
    if material == "custom" or density is None:
        d0 = dens_by.get(material, settings.get("last_density", 1.0)) or 1.0
        density = rs.GetReal("密度 g/cm3 を入力", d0, 0.01, 30.0)
        if density is None:
            return
    dens_by[material] = density

    # 任意: 材料費（¥/kg）。空(0)なら金額を出さない。
    price_by = settings.get("unit_price_by_material", {}) or {}
    up0 = price_by.get(material, 0.0) or 0.0
    unit_price = rs.GetReal("材料費 円/kg（不要なら0）", up0, 0.0, 1000000.0)
    if unit_price is None:
        unit_price = 0.0
    price_by[material] = unit_price

    weight, volume_m3, cost = mass.compute_mass(vol_mm3, density,
                                                unit_price if unit_price > 0 else None)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 設定だけ保存（前回値を覚える）。**オブジェクトUserTextへは書き込まない・CSVも保存しない**
    # （Mass は軽い重量計算ツール。確認ダイアログを毎回出さない）。
    mass.save_settings({
        "last_material": material, "last_density": density,
        "density_by_material": dens_by, "unit_price_by_material": price_by,
    }, now_str=now)

    cost_s = "（単価未入力）" if cost is None else "%s 円" % format(int(round(cost)), ",")
    lines = [
        "----- 重量計算（Mass）-----",
        "入力オブジェクト数   : %d" % n_in,
        "体積計算ジオメトリ数 : %d" % n_vol,
        "使用素材             : %s" % mass.material_label(material),
        "密度                 : %s g/cm3" % _g(density),
        "モデル単位           : %s" % unit_label,
        "体積                 : %s m3" % _g(round(volume_m3, 6)),
        "重量                 : %s kg" % (_g(round(weight, 3)) if weight else "0"),
        "概算材料費           : %s" % cost_s,
        "失敗数               : %d" % n_fail,
    ]
    msg = "\n".join(lines)
    try:
        Rhino.RhinoApp.WriteLine(msg)
    except Exception:
        pass
    rs.MessageBox(msg, 0, "重量計算（Mass）")
    return msg


def _g(v):
    try:
        return "%g" % float(v)
    except (TypeError, ValueError):
        return str(v)


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as e:
        print("[mass_rhino] " + str(e))
        raise SystemExit(1)
