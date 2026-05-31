#! python 3
# -*- coding: utf-8 -*-
"""Rhino 8 ScriptEditor / Python 3 / RhinoCommon 専用: Quote（概算見積）。

将来のRhinoコマンド: Quote / _Quote。Mass（重量計算）とは別物。
選択オブジェクトの volume から重量を出し、公開用参考価格の「概算用単価カテゴリ」の
円/kg を掛けて概算見積を出す。**重量計算用素材（密度）と 概算用単価カテゴリ（円/kg）は分離**。

UI表示はすべて日本語（recommended/conservative 等は見せない）。内部値・CSVキー・JSONキーは英語。
価格は公開用参考価格（実取引価格ではない）。設定: ~/Documents/RhinoScripts/quote_settings.json
"""

import os
import sys

RHINO_HINT = ("このスクリプトは Rhino 8 の ScriptEditor (Python 3 / RhinoCommon) 専用です。\n"
              "_ScriptEditor で言語を 'Python 3 (CPython / RhinoCommon)' にして実行してください。")
PUBLIC_DIR_CANDIDATES = [
    "./public_reference_data",
    os.path.join(os.path.expanduser("~"),
                 "Documents/claude/projects/steel-estimator/public_reference_data"),
]


QUOTE_VERSION = "quote-debug-2026-05-31"


def _dbg(msg):
    """Rhinoコマンドラインとstdoutへデバッグ出力（取り違え・落下点の特定用）。"""
    try:
        import Rhino
        Rhino.RhinoApp.WriteLine("[Quote] " + msg)
    except Exception:
        pass
    try:
        print("[Quote] " + msg)
    except Exception:
        pass


def _fmt_yen(v):
    """金額をNone安全に整形（int(None)/format(None)で落ちない）。"""
    if v in (None, ""):
        return "—"
    try:
        return "%s 円" % format(int(round(float(v))), ",")
    except (TypeError, ValueError):
        return "—"


def _fmt_kg(v):
    """重量kgをNone安全に整形。"""
    if v in (None, ""):
        return "0"
    try:
        return "%g" % round(float(v), 3)
    except (TypeError, ValueError):
        return "0"


def _label_to_value(chosen_label, labels, values, default_value):
    """ListBoxで選ばれた日本語ラベルを内部値へ安全に変換（.indexのValueErrorを防ぐ）。

    見つからない場合は default_value を返し、無言で落ちない。
    """
    if chosen_label in labels:
        return values[labels.index(chosen_label)]
    # 前後空白などの揺れを吸収して再照合
    cl = (chosen_label or "").strip()
    for i, lb in enumerate(labels):
        if (lb or "").strip() == cl:
            return values[i]
    _dbg("label変換に失敗→既定値を使用: chosen=%r" % chosen_label)
    return default_value


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
    print("----- Quote script -----")
    print("path: %s" % path)
    print("version: %s" % QUOTE_VERSION)


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
    # Rhinoセッションは sys.modules を跨いで保持するため、古いcoreが
    # キャッシュされていると新属性(QUOTE_PRICE_FACTOR等)が無く落ちる。
    # 必ず最新ファイルから読み直す。
    sys.modules.pop("steel_estimate_core_for_rhino", None)
    import steel_estimate_core_for_rhino as core
    return core


def _find_public_dir():
    for d in PUBLIC_DIR_CANDIDATES:
        if os.path.exists(os.path.join(d, "public_plate_reference_prices.csv")):
            return d
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        cand = os.path.join(os.path.dirname(here), "public_reference_data")
        if os.path.exists(os.path.join(cand, "public_plate_reference_prices.csv")):
            return cand
    except Exception:
        pass
    return PUBLIC_DIR_CANDIDATES[0]


def _unit_scale(doc):
    name = str(getattr(doc, "ModelUnitSystem", "Millimeters"))
    scale = {"Millimeters": 1.0, "Centimeters": 10.0, "Meters": 1000.0,
             "Inches": 25.4, "Feet": 304.8}.get(name, 1.0)
    label = {"Millimeters": "mm", "Centimeters": "cm", "Meters": "m",
             "Inches": "inch", "Feet": "feet"}.get(name, name)
    return scale, label


def _sum_volume_mm3(doc, Rhino, obj_ids):
    G = Rhino.Geometry
    scale3 = _unit_scale(doc)[0] ** 3
    total, n_in, n_vol = 0.0, 0, 0
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
            elif isinstance(geom, G.Mesh) and geom.IsClosed:
                vmp = G.VolumeMassProperties.Compute(geom)
                if vmp:
                    total += float(vmp.Volume) * scale3
                    n_vol += 1
        except Exception:
            continue
    return total, n_in, n_vol


def _quote_main():
    _require_rhino()
    import Rhino
    import scriptcontext as sc
    import rhinoscriptsyntax as rs
    from datetime import datetime

    _dbg("step: start")
    core = _load_core()
    # 依存core取り違え/古いキャッシュ検出用バナー
    try:
        _dbg("----- Quote dependency -----")
        _dbg("core path: %s" % os.path.abspath(core.__file__))
        _dbg("core version: %s" % getattr(core, "CORE_VERSION", "(なし=古いcore)"))
        _dbg("QUOTE_PRICE_FACTOR: %s" % getattr(core, "QUOTE_PRICE_FACTOR", "(なし=古いcore)"))
    except Exception:
        pass
    doc = sc.doc
    settings = core.load_settings(core.quote_settings_path())
    catalog = core.build_price_catalog(core.load_reference(_find_public_dir()))
    scale, unit_label = _unit_scale(doc)

    ids = rs.GetObjects("見積するオブジェクトを選択（未選択でEnterなら全件）", preselect=True, select=False)
    if not ids:
        ids = [o.Id for o in doc.Objects]
    raw_volume_mm3, n_in, n_vol = _sum_volume_mm3(doc, Rhino, ids)
    _dbg("selected objects: %d / geom with volume: %d / raw_volume_mm3: %s"
         % (n_in, n_vol, core._g(raw_volume_mm3)))
    if raw_volume_mm3 <= 0:
        rs.MessageBox("体積が取れる閉ソリッドがありません。閉じたポリサーフェスにしてください。",
                      0, "概算見積（Quote）")
        return

    # A) 重量計算用素材（密度）— 金属3択・日本語表示
    mat_keys = [m for m, _ in core.DENSITY_MATERIALS]  # steel / stainless / aluminum
    mat_labels = [core.material_label(k) for k in mat_keys]
    last_mat = settings.get("last_density_material", "steel")
    a_default = core.material_label(last_mat if last_mat in mat_keys else "steel")
    chosen_mat_label = rs.ListBox(
        mat_labels,
        "金属見積用に、体積から重量を計算するための素材を選びます。"
        "細かい板厚・パイプ種別・単価カテゴリは次の画面で選びます。",
        "重量計算用素材を選択", a_default)
    if chosen_mat_label is None:
        _dbg("素材選択キャンセル")
        return
    material = _label_to_value(chosen_mat_label, mat_labels, mat_keys, "steel")
    density = core.density_for_material(material)
    _dbg("step: density selected / density_material=%s / density=%s"
         % (material, core._g(density)))

    # B) 概算用単価カテゴリ — 日本語ラベル
    labels = [e["label"] for e in catalog]
    last_key = settings.get("last_price_category", "")
    b_default = next((e["label"] for e in catalog if e["key"] == last_key),
                     labels[0] if labels else None)
    chosen_label = rs.ListBox(labels, "この重量を、どの概算単価で計算しますか？",
                              "概算用単価を選択", b_default)
    if chosen_label is None:
        _dbg("単価カテゴリ選択キャンセル")
        return
    entry = next((e for e in catalog if e["label"] == chosen_label), None)
    _dbg("step: price category selected / key=%s / rec=%s / con=%s"
         % ((entry["key"] if entry else "(なし)"),
            core._g(entry.get("recommended_per_kg")) if entry else "",
            core._g(entry.get("conservative_per_kg")) if entry else ""))

    # 見積方法（pricing_mode）— 日本語表示、内部値へ安全に戻す
    modes = ["recommended", "conservative", "manual"]
    mode_labels = [core.pricing_mode_label(m) for m in modes]
    last_mode = settings.get("last_pricing_mode", "recommended")
    m_default = core.pricing_mode_label(last_mode if last_mode in modes else "recommended")
    chosen_mode_label = rs.ListBox(
        mode_labels,
        "通常は「通常見積（中央値）」を選んでください。高めに見る場合は「安全側見積（最大値）」、"
        "自分で単価を入れる場合は「手入力」を選びます。",
        "見積方法を選択", m_default)
    if chosen_mode_label is None:
        _dbg("見積方法選択キャンセル")
        return
    mode = _label_to_value(chosen_mode_label, mode_labels, modes, "recommended")
    _dbg("step: pricing mode selected / label=%r -> mode=%s" % (chosen_mode_label, mode))

    manual_by_cat = settings.get("manual_unit_prices_by_category", {}) or {}
    manual_value = None
    if mode == "manual":
        d0 = manual_by_cat.get(entry["key"] if entry else "", 0.0) or 200.0
        manual_value = rs.GetReal("手入力の単価 円/kg（税抜）", d0, 0.0, 1000000.0)
        if manual_value is None:
            return
        if entry:
            manual_by_cat[entry["key"]] = manual_value

    # 安全係数（公開参考価格の通常/安全側に掛ける。manualには掛けない）。設定可、既定1.2。
    factor = core._f(settings.get("quote_price_factor")) or core.QUOTE_PRICE_FACTOR
    unit_price, pwarn = core.resolve_unit_price(entry, mode, manual_value, factor=factor)
    _dbg("step: unit price resolved / unit_price_used=%s / warning=%s"
         % (core._g(unit_price), pwarn or "なし"))
    weight_kg, cost, volume_m3 = core.compute_cost(raw_volume_mm3, density, unit_price)
    _dbg("step: compute / weight_kg=%s / cost_jpy=%s"
         % (core._g(weight_kg), core._g(cost)))
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    core.save_settings({
        "last_density_material": material,
        "last_density_value": density,
        "last_price_category": entry["key"] if entry else "",
        "last_pricing_mode": mode,
        "manual_unit_prices_by_category": manual_by_cat,
        "quote_price_factor": factor,
    }, path=core.quote_settings_path(), now_str=now)

    # UserText（quote_* 接頭辞。Massと混ざらない）
    try:
        for oid in ids:
            obj = doc.Objects.FindId(oid)
            if not obj:
                continue
            a = obj.Attributes
            a.SetUserString("quote_density_material", material)
            a.SetUserString("quote_density_value", str(density))
            a.SetUserString("quote_price_category", entry["key"] if entry else "")
            a.SetUserString("quote_pricing_mode", mode)
            a.SetUserString("quote_unit_price_jpy_per_kg", "" if unit_price is None else str(unit_price))
            a.SetUserString("quote_volume_m3", str(round(volume_m3, 6)))
            a.SetUserString("quote_weight_kg", "" if weight_kg is None else str(round(weight_kg, 3)))
            a.SetUserString("quote_cost_jpy", "" if cost is None else str(int(round(cost))))
            a.SetUserString("quote_calculated_at", now)
            doc.Objects.ModifyAttributes(obj, a, True)
    except Exception:
        pass

    # 表示用: 元単価（manualは係数なし）と補正後単価
    if mode == "manual":
        raw_disp = "手入力（安全係数なし）"
        up_s = "—（手入力が必要）" if unit_price is None else "%s 円/kg（手入力）" % core._g(unit_price)
    else:
        raw = (entry.get("conservative_per_kg") if mode in ("conservative", "max")
               else entry.get("recommended_per_kg")) if entry else None
        if raw is None and entry:
            raw = entry.get("recommended_per_kg")
        raw_disp = ("%s 円/kg" % core._g(raw)) if raw is not None else "—"
        up_s = ("—（手入力が必要）" if unit_price is None
                else "%s 円/kg（元%s × 安全係数%s、10円切上）"
                % (core._g(unit_price), core._g(raw), core._g(factor)))
    cost_s = _fmt_yen(cost)
    if cost is None:
        # 重量までは出して理由を明示（無言終了させない）
        pwarn = (pwarn or "") + ("; " if pwarn else "") + "単価が取得できないため、材料費は未計算です"
    lines = [
        "----- 概算見積（Quote）-----",
        "入力オブジェクト数   : %d" % n_in,
        "体積計算ジオメトリ数 : %d" % n_vol,
        "重量計算用素材       : %s" % core.material_label(material),
        "密度                 : %s g/cm3" % core._g(density),
        "モデル単位           : %s" % unit_label,
        "体積                 : %s m3" % core._g(round(volume_m3, 6) if volume_m3 else 0),
        "重量                 : %s kg" % _fmt_kg(weight_kg),
        "概算用単価カテゴリ   : %s" % (entry["key"] if entry else "(なし)"),
        "見積方法             : %s" % core.pricing_mode_label(mode),
        "安全係数             : %s%s" % (core._g(factor),
                                         "（manualは非適用）" if mode == "manual" else ""),
        "元単価               : %s" % raw_disp,
        "kg単価（補正後）     : %s" % up_s,
        "概算材料費           : %s" % cost_s,
        "失敗                 : 0",
        "注意事項             : %s" % (pwarn or "公開参考価格による概算。発注前に実見積で確認。"),
    ]
    msg = "\n".join(lines)
    _dbg("step: show result")
    try:
        Rhino.RhinoApp.WriteLine(msg)
    except Exception:
        pass
    rs.MessageBox(msg, 0, "概算見積（Quote）")
    return msg


def main():
    """エントリ。例外を絶対に無言で潰さず、traceback と MessageBox を必ず出す。"""
    _print_banner()
    if not running_in_rhino():
        raise RuntimeError(RHINO_HINT)
    import traceback
    try:
        return _quote_main()
    except Exception:
        tb = traceback.format_exc()
        try:
            import Rhino
            Rhino.RhinoApp.WriteLine("[Quote] ERROR:\n" + tb)
        except Exception:
            pass
        print("[Quote] ERROR:\n" + tb)
        try:
            import rhinoscriptsyntax as rs
            rs.MessageBox("Quote処理中にエラーが発生しました。詳細はRhinoコマンド履歴を確認してください。\n\n"
                          + tb.strip().splitlines()[-1], 16, "概算見積（Quote）エラー")
        except Exception:
            pass
        return None


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as e:
        print("[quote_estimate_rhino] " + str(e))
        raise SystemExit(1)
