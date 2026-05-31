"""Rhino 8 ScriptEditor 用: 開いているモデルから rhino_objects.csv を出力する。

使い方（要約）:
  1. Rhino 8 で対象の .3dm を開く。
  2. _ScriptEditor を実行し、本ファイルを開く。
  3. 実行（Run）。保存ダイアログが出れば出力先を選ぶ。出なければ
     モデルと同じフォルダ、未保存なら Desktop に rhino_objects.csv を書く。
  4. 出力CSVを steel-estimator の summarize-layers に渡す。

出力スキーマは steel_estimator の rhino_objects.csv と完全互換（UTF-8 BOM）。

設計方針:
  - 全レイヤー・全オブジェクトを出力（補助線・注釈も除外しない。除外は後段の
    layer_mapping.csv で行う）。
  - 値が取れない場合は 0 / 空欄にし、理由を notes に書く（エラーで止めない）。
  - モデル単位は mm に換算して出力。未対応単位は notes に warning。
  - Block(InstanceObject) は v1では展開しない（notes に明記、bboxのみ出力）。

本ファイルは Rhino 内実行が前提のため steel_estimator パッケージに依存しない
（RhinoCommon の import は main 内で遅延実行し、純粋関数はテスト可能に保つ）。
"""

# RhinoCommon / scriptcontext は main() 内で遅延 import する（本モジュール先頭は純粋）。

HEADERS = [
    "file_name", "layer_name", "object_id", "object_name", "object_type",
    "object_count", "object_area_mm2", "object_volume_mm3", "object_curve_length_mm",
    "bounding_box_width_mm", "bounding_box_height_mm", "bounding_box_depth_mm",
    "is_closed_curve", "is_closed_brep", "is_surface", "is_mesh", "is_curve", "notes",
]

# モデル単位名 → mm 換算係数（steel_estimator.rhino_csv と同一仕様）
UNIT_SCALE_TO_MM = {
    "millimeters": 1.0, "centimeters": 10.0, "meters": 1000.0,
    "inches": 25.4, "feet": 304.8,
    "microns": 0.001, "decimeters": 100.0, "kilometers": 1_000_000.0,
    "mils": 0.0254, "yards": 914.4, "miles": 1_609_344.0,
    "nanometers": 1e-6,
}


def scale_for_unit_name(unit_name):
    """単位名（小文字化前提でなくてもよい）から (scale_to_mm, warning_or_empty)。"""
    key = (unit_name or "").strip().lower()
    if key in UNIT_SCALE_TO_MM:
        return UNIT_SCALE_TO_MM[key], ""
    return 1.0, "unsupported model unit '%s'; exported without mm conversion (scale=1)" % unit_name


def bool_str(value):
    return "true" if value else "false"


def add_note(notes, msg):
    if not msg:
        return notes
    return (notes + "; " + msg).strip("; ") if notes else msg


def make_row(file_name, layer_name, object_id, object_name, object_type,
             area_mm2=0.0, volume_mm3=0.0, curve_len_mm=0.0,
             bbw=0.0, bbh=0.0, bbd=0.0,
             is_closed_curve=False, is_closed_brep=False,
             is_surface=False, is_mesh=False, is_curve=False, notes=""):
    """1オブジェクト分の行 dict を HEADERS の順序で組み立てる（純粋関数）。"""
    return {
        "file_name": file_name,
        "layer_name": layer_name,
        "object_id": object_id,
        "object_name": object_name or "",
        "object_type": object_type,
        "object_count": 1,
        "object_area_mm2": _num(area_mm2),
        "object_volume_mm3": _num(volume_mm3),
        "object_curve_length_mm": _num(curve_len_mm),
        "bounding_box_width_mm": _num(bbw),
        "bounding_box_height_mm": _num(bbh),
        "bounding_box_depth_mm": _num(bbd),
        "is_closed_curve": bool_str(is_closed_curve),
        "is_closed_brep": bool_str(is_closed_brep),
        "is_surface": bool_str(is_surface),
        "is_mesh": bool_str(is_mesh),
        "is_curve": bool_str(is_curve),
        "notes": notes,
    }


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0
    if f != f:  # NaN
        return 0
    # 整数なら整数、端数があれば丸めて出す
    return int(round(f)) if abs(f - round(f)) < 1e-9 else round(f, 4)


def write_csv(path, rows):
    """UTF-8 with BOM で CSV を書き出す（Excel互換）。"""
    import csv
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HEADERS)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return len(rows)


# ============================================================
# 以降は Rhino 実行時のみ使用（RhinoCommon 依存）
# ============================================================

def _full_layer_path(doc, layer_index):
    """フルレイヤーパスを '親::子' 形式で返す。"""
    try:
        layer = doc.Layers[layer_index]
    except Exception:
        return ""
    try:
        fp = layer.FullPath  # Rhino は '::' 区切りで返す
        if fp:
            return fp
    except Exception:
        pass
    # フォールバック: 親を辿って手組み
    names = [layer.Name]
    parent_id = layer.ParentLayerId
    guard = 0
    while parent_id and str(parent_id) != "00000000-0000-0000-0000-000000000000" and guard < 50:
        parent = doc.Layers.FindId(parent_id)
        if not parent:
            break
        names.insert(0, parent.Name)
        parent_id = parent.ParentLayerId
        guard += 1
    return "::".join(names)


def _safe_area(geom, Rhino):
    try:
        amp = Rhino.Geometry.AreaMassProperties.Compute(geom)
        if amp:
            return float(amp.Area), ""
    except Exception as e:
        return 0.0, "area compute failed: %s" % e
    return 0.0, "area not available"


def _safe_volume(geom, Rhino):
    try:
        vmp = Rhino.Geometry.VolumeMassProperties.Compute(geom)
        if vmp:
            return float(vmp.Volume), ""
    except Exception as e:
        return 0.0, "volume compute failed: %s" % e
    return 0.0, "volume not available"


def _classify_and_measure(geom, obj, Rhino, scale):
    """geometry から (object_type, fields dict, notes) を返す。すべて mm 換算済み。

    fields: area_mm2, volume_mm3, curve_len_mm, flags(is_*)。
    """
    G = Rhino.Geometry
    s1, s2, s3 = scale, scale * scale, scale * scale * scale
    notes = ""
    f = dict(area=0.0, volume=0.0, length=0.0,
             is_closed_curve=False, is_closed_brep=False,
             is_surface=False, is_mesh=False, is_curve=False)

    # InstanceObject(Block) は展開しない
    try:
        if isinstance(obj, Rhino.DocObjects.InstanceObject):
            return "InstanceObject", f, "block instance not expanded"
    except Exception:
        pass

    if isinstance(geom, G.Curve):
        f["is_curve"] = True
        try:
            f["length"] = geom.GetLength() * s1
        except Exception:
            notes = add_note(notes, "curve length failed")
        try:
            f["is_closed_curve"] = bool(geom.IsClosed)
        except Exception:
            pass
        # 閉じた平面曲線なら面積を試す
        if f["is_closed_curve"]:
            try:
                if geom.IsPlanar():
                    a, msg = _safe_area(geom, Rhino)
                    f["area"] = a * s2
                    notes = add_note(notes, msg)
            except Exception:
                notes = add_note(notes, "planar area failed")
        return "Curve", f, notes

    if isinstance(geom, G.Extrusion):
        notes = add_note(notes, "extrusion converted to brep")
        try:
            brep = geom.ToBrep()
        except Exception:
            brep = None
        if brep:
            return _measure_brep(brep, "Extrusion", f, notes, Rhino, s2, s3)
        return "Extrusion", f, add_note(notes, "extrusion->brep failed")

    if isinstance(geom, G.Brep):
        otype = "Surface" if (geom.Faces.Count == 1 and not geom.IsSolid) else "Brep"
        return _measure_brep(geom, otype, f, notes, Rhino, s2, s3)

    if isinstance(geom, G.Surface):
        f["is_surface"] = True
        a, msg = _safe_area(geom, Rhino)
        f["area"] = a * s2
        return "Surface", f, add_note(notes, msg)

    if isinstance(geom, G.Mesh):
        f["is_mesh"] = True
        try:
            f["is_closed_brep"] = bool(geom.IsClosed)
        except Exception:
            pass
        a, amsg = _safe_area(geom, Rhino)
        f["area"] = a * s2
        notes = add_note(notes, amsg)
        if f["is_closed_brep"]:
            v, vmsg = _safe_volume(geom, Rhino)
            f["volume"] = v * s3
            notes = add_note(notes, vmsg)
        return "Mesh", f, notes

    if isinstance(geom, G.Point):
        return "Point", f, notes

    # 注釈系
    try:
        if isinstance(geom, G.AnnotationBase) or isinstance(geom, G.TextEntity):
            return "Annotation", f, notes
    except Exception:
        pass

    return "Other", f, add_note(notes, "unsupported geometry type")


def _measure_brep(brep, otype, f, notes, Rhino, s2, s3):
    try:
        if brep.Faces.Count >= 1:
            f["is_surface"] = True
    except Exception:
        pass
    try:
        f["is_closed_brep"] = bool(brep.IsSolid)
    except Exception:
        pass
    a, amsg = _safe_area(brep, Rhino)
    f["area"] = a * s2
    notes = add_note(notes, amsg)
    if f["is_closed_brep"]:
        v, vmsg = _safe_volume(brep, Rhino)
        f["volume"] = v * s3
        notes = add_note(notes, vmsg)
    return otype, f, notes


def _resolve_output_path(doc):
    """出力先を決める。保存ダイアログ→モデル同階層→Desktop の順。"""
    import os
    # 1) 保存ダイアログ
    try:
        import rhinoscriptsyntax as rs
        p = rs.SaveFileName("rhino_objects.csv の保存先", "CSV Files (*.csv)|*.csv||",
                            None, "rhino_objects.csv")
        if p:
            return p, ""
    except Exception:
        pass
    # 2) モデルと同じフォルダ
    try:
        if doc.Path:
            folder = os.path.dirname(doc.Path)
            if folder and os.path.isdir(folder):
                return os.path.join(folder, "rhino_objects.csv"), ""
    except Exception:
        pass
    # 3) Desktop
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    if not os.path.isdir(desktop):
        desktop = os.path.expanduser("~")
    return os.path.join(desktop, "rhino_objects.csv"), "output fell back to Desktop (model unsaved)"


RHINO_HINT = (
    "このスクリプトは Rhino 8 の ScriptEditor (Python 3 / RhinoCommon) 専用です。\n"
    "Rhino を起動し、_ScriptEditor で言語を 'Python 3 (CPython / RhinoCommon)' にして実行してください。"
)


def running_in_rhino() -> bool:
    """RhinoCommon が利用可能か（通常Pythonでは False）。"""
    try:
        import Rhino  # noqa: F401
        import scriptcontext  # noqa: F401
        return True
    except Exception:
        return False


def _require_rhino():
    if not running_in_rhino():
        raise RuntimeError(RHINO_HINT)


def main():
    import os
    _require_rhino()
    import scriptcontext as sc
    import Rhino

    doc = sc.doc

    # ファイル名
    try:
        file_name = os.path.basename(doc.Path) if doc.Path else "unsaved.3dm"
    except Exception:
        file_name = "unsaved.3dm"

    # 単位 → mm 換算
    try:
        unit_name = str(doc.ModelUnitSystem)
    except Exception:
        unit_name = "Millimeters"
    scale, unit_warn = scale_for_unit_name(unit_name)

    rows = []
    area_cnt = vol_cnt = curve_cnt = note_cnt = 0
    layers = set()

    for obj in doc.Objects:
        try:
            geom = obj.Geometry
            attrs = obj.Attributes
            layer_name = _full_layer_path(doc, attrs.LayerIndex)
            layers.add(layer_name)
            object_id = str(obj.Id)
            object_name = ""
            try:
                object_name = attrs.Name or ""
            except Exception:
                pass

            otype, f, notes = _classify_and_measure(geom, obj, Rhino, scale)

            # bounding box（取れれば mm 換算して出す）
            bbw = bbh = bbd = 0.0
            try:
                bb = geom.GetBoundingBox(True)
                if bb and bb.IsValid:
                    bbw = (bb.Max.X - bb.Min.X) * scale
                    bbh = (bb.Max.Y - bb.Min.Y) * scale
                    bbd = (bb.Max.Z - bb.Min.Z) * scale
            except Exception:
                notes = add_note(notes, "bbox failed")

            if unit_warn:
                notes = add_note(notes, unit_warn)
            elif scale != 1.0:
                notes = add_note(notes, "converted to mm (scale=%g)" % scale)

            row = make_row(
                file_name, layer_name, object_id, object_name, otype,
                area_mm2=f["area"], volume_mm3=f["volume"], curve_len_mm=f["length"],
                bbw=bbw, bbh=bbh, bbd=bbd,
                is_closed_curve=f["is_closed_curve"], is_closed_brep=f["is_closed_brep"],
                is_surface=f["is_surface"], is_mesh=f["is_mesh"], is_curve=f["is_curve"],
                notes=notes,
            )
            rows.append(row)
            if f["area"] > 0:
                area_cnt += 1
            if f["volume"] > 0:
                vol_cnt += 1
            if f["length"] > 0:
                curve_cnt += 1
            if notes:
                note_cnt += 1
        except Exception as e:
            # 1オブジェクトの失敗で全体を止めない
            rows.append(make_row(file_name, "", "", "", "Other",
                                 notes="export error: %s" % e))
            note_cnt += 1

    out_path, out_warn = _resolve_output_path(doc)
    write_csv(out_path, rows)

    lines = [
        "=== export_rhino_objects 完了 ===",
        "出力パス        : %s" % out_path,
        "出力オブジェクト数: %d" % len(rows),
        "レイヤー数      : %d" % len(layers),
        "面積取得件数    : %d" % area_cnt,
        "体積取得件数    : %d" % vol_cnt,
        "曲線長取得件数  : %d" % curve_cnt,
        "notesあり件数   : %d" % note_cnt,
        "モデル単位      : %s (scale_to_mm=%g)" % (unit_name, scale),
    ]
    if unit_warn:
        lines.append("WARNING        : %s" % unit_warn)
    if out_warn:
        lines.append("NOTE           : %s" % out_warn)
    msg = "\n".join(lines)
    try:
        Rhino.RhinoApp.WriteLine(msg)
    except Exception:
        pass
    try:
        import rhinoscriptsyntax as rs
        rs.MessageBox("rhino_objects.csv を出力しました:\n%s\n\nオブジェクト %d / レイヤー %d"
                      % (out_path, len(rows), len(layers)), 0, "export_rhino_objects")
    except Exception:
        pass
    print(msg)
    return out_path


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as e:
        print("[export_rhino_objects] " + str(e))
        raise SystemExit(1)
