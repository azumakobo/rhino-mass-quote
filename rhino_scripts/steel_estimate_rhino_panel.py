"""Rhino 8 ScriptEditor / Python 3 / RhinoCommon 専用: Rhino内 概算見積ウィンドウ。

★ 通常の python では動きません（RhinoCommon / Eto が必要）。Rhino 8 の `_ScriptEditor` で
   言語を「Python 3 (CPython / RhinoCommon)」にして実行してください。

このパネルは **表示専用＋CSV出力** の最小版です（単価/pricing_mode編集は後続フェーズ）。
標準方針: 鋼材はポリサーフェス→体積→重量(volume_to_weight)。価格は public_reference_data の
公開用参考価格（**実取引価格ではありません**）。

導線: モデルを開く → 本スクリプトを Run → ウィンドウでレイヤー別金額と合計を確認 → CSV出力。
"""

import os
import sys

DEFAULT_TAX_RATE = 0.10
PUBLIC_DIR_CANDIDATES = [
    "./public_reference_data",
    os.path.join(os.path.expanduser("~"),
                 "Documents/claude/projects/steel-estimator/public_reference_data"),
]

RHINO_HINT = (
    "このスクリプトは Rhino 8 の ScriptEditor (Python 3 / RhinoCommon) 専用です。\n"
    "Rhino を起動し、_ScriptEditor で言語を 'Python 3 (CPython / RhinoCommon)' にして実行してください。"
)


def running_in_rhino():
    try:
        import Rhino  # noqa: F401
        import scriptcontext  # noqa: F401
        return True
    except Exception:
        return False


def _require_rhino():
    if not running_in_rhino():
        raise RuntimeError(RHINO_HINT)


def _load_core():
    """同フォルダの steel_estimate_core_for_rhino を読み込む。"""
    try:
        here = os.path.dirname(os.path.abspath(__file__))
    except Exception:
        here = os.getcwd()
    if here not in sys.path:
        sys.path.insert(0, here)
    import steel_estimate_core_for_rhino as core
    return core


def _find_public_dir(core):
    for d in PUBLIC_DIR_CANDIDATES:
        if os.path.exists(os.path.join(d, "public_plate_reference_prices.csv")):
            return d
    # スクリプトからの相対（rhino_scripts/.. /public_reference_data）
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        cand = os.path.join(os.path.dirname(here), "public_reference_data")
        if os.path.exists(os.path.join(cand, "public_plate_reference_prices.csv")):
            return cand
    except Exception:
        pass
    return PUBLIC_DIR_CANDIDATES[0]


# ============================================================
# Rhino ドキュメント走査（レイヤー別集計）
# ============================================================

def _unit_scale(doc):
    name = str(getattr(doc, "ModelUnitSystem", "Millimeters"))
    return {"Millimeters": 1.0, "Centimeters": 10.0, "Meters": 1000.0,
            "Inches": 25.4, "Feet": 304.8}.get(name, 1.0), name


def scan_document(doc, Rhino):
    """レイヤー別に volume_mm3 / area_m2 / object_count を集計して返す。"""
    G = Rhino.Geometry
    scale, _ = _unit_scale(doc)
    s2, s3 = scale * scale, scale * scale * scale
    agg = {}  # layer_name -> dict

    def bucket(layer):
        return agg.setdefault(layer, {"layer_name": layer, "volume_mm3": 0.0,
                                      "area_mm2": 0.0, "object_count": 0})

    for obj in doc.Objects:
        try:
            geom = obj.Geometry
            layer = doc.Layers[obj.Attributes.LayerIndex].FullPath
            b = bucket(layer)
            b["object_count"] += 1
            # 体積（閉じた Brep / Extrusion / Mesh）
            brep = None
            if isinstance(geom, G.Extrusion):
                brep = geom.ToBrep(True)
            elif isinstance(geom, G.Brep):
                brep = geom
            if brep is not None and brep.IsSolid:
                vmp = G.VolumeMassProperties.Compute(brep)
                if vmp:
                    b["volume_mm3"] += float(vmp.Volume) * s3
                amp = G.AreaMassProperties.Compute(brep)
                # 面積は板材判定用に保持しない（ソリッドは体積優先）
            elif isinstance(geom, G.Mesh) and geom.IsClosed:
                vmp = G.VolumeMassProperties.Compute(geom)
                if vmp:
                    b["volume_mm3"] += float(vmp.Volume) * s3
            else:
                # 面積（サーフェス / 閉じた平面曲線）
                amp = None
                if isinstance(geom, (G.Brep, G.Surface)):
                    amp = G.AreaMassProperties.Compute(geom)
                elif isinstance(geom, G.Curve) and geom.IsClosed and geom.IsPlanar():
                    amp = G.AreaMassProperties.Compute(geom)
                if amp:
                    b["area_mm2"] += float(amp.Area) * s2
        except Exception:
            continue

    out = []
    for layer, b in agg.items():
        out.append({"layer_name": layer, "volume_mm3": round(b["volume_mm3"], 1),
                    "area_m2": round(b["area_mm2"] / 1_000_000.0, 6),
                    "object_count": b["object_count"]})
    return out


# ============================================================
# UI（Eto.Forms）
# ============================================================

# mass中心の表示列（volume/weight/単価/金額を中心に。area_m2は補助で末尾）
COLS = ["layer_name", "object_count", "category", "calc_type",
        "volume_mm3", "weight_kg", "density_g_cm3",
        "unit_price_ex_tax", "amount_ex_tax", "amount_inc_tax",
        "warning", "area_m2"]


def _rows_to_grid(rows):
    return [[str(r.get(c, "")) for c in COLS] for r in rows]


def main():
    _require_rhino()
    import Rhino
    import scriptcontext as sc
    import Eto.Forms as forms
    import Eto.Drawing as drawing

    core = _load_core()
    doc = sc.doc
    public_dir = _find_public_dir(core)
    ref = core.load_reference(public_dir)
    tax_rate = DEFAULT_TAX_RATE

    state = {"rows": [], "totals": {}, "model_path": getattr(doc, "Path", "") or ""}

    def recompute():
        aggs = scan_document(doc, Rhino)
        rows, totals = core.estimate_all(aggs, ref, tax_rate, "median")
        state["rows"], state["totals"] = rows, totals
        return rows, totals

    recompute()

    form = forms.Form()
    form.Title = "Steel Estimator"
    form.ClientSize = drawing.Size(1000, 560)
    form.Padding = drawing.Padding(8)

    layout = forms.DynamicLayout()
    layout.Spacing = drawing.Size(6, 6)

    note = forms.Label()
    note.Text = ("公開用参考価格による概算です（実取引価格ではありません） / 税率 %d%% / "
                 "鋼材はポリサーフェス体積→重量 / 公開: %s" % (int(tax_rate * 100), public_dir))

    btn_recalc = forms.Button()
    btn_recalc.Text = "再計算"
    btn_csv = forms.Button()
    btn_csv.Text = "CSV出力"
    path_label = forms.Label()
    path_label.Text = ""

    grid = forms.GridView()
    grid.ShowHeader = True
    for i, c in enumerate(COLS):
        col = forms.GridColumn()
        col.HeaderText = c
        col.DataCell = forms.TextBoxCell(i)
        col.Resizable = True
        grid.Columns.Add(col)
    grid.DataStore = _rows_to_grid(state["rows"])

    total_label = forms.Label()

    def refresh_totals():
        t = state["totals"]
        total_label.Text = (
            "税抜合計 ¥{ex:,}   消費税 ¥{tax:,}   税込合計 ¥{inc:,}\n"
            "recommended(中央値) 税抜¥{rex:,} / 税込¥{rinc:,}   "
            "conservative(最大値) 税抜¥{cex:,} / 税込¥{cinc:,}".format(
                ex=int(t.get("subtotal_ex_tax", 0)), tax=int(t.get("tax_amount", 0)),
                inc=int(t.get("subtotal_inc_tax", 0)),
                rex=int(t.get("recommended_ex_tax", 0)), rinc=int(t.get("recommended_inc_tax", 0)),
                cex=int(t.get("conservative_ex_tax", 0)), cinc=int(t.get("conservative_inc_tax", 0))))

    refresh_totals()

    def on_recalc(sender, e):
        recompute()
        grid.DataStore = _rows_to_grid(state["rows"])
        refresh_totals()
        path_label.Text = "再計算しました"

    def on_csv(sender, e):
        out = core.resolve_output_path(state["model_path"])
        core.write_csv(out, state["rows"])
        path_label.Text = "CSV出力: %s" % out
        try:
            Rhino.RhinoApp.WriteLine("[Steel Estimator] CSV出力: %s" % out)
        except Exception:
            pass

    btn_recalc.Click += on_recalc
    btn_csv.Click += on_csv

    top = forms.DynamicLayout()
    top.AddRow(btn_recalc, btn_csv, path_label, None)

    layout.AddRow(note)
    layout.AddRow(top)
    layout.Add(grid, yscale=True)
    layout.AddRow(total_label)
    form.Content = layout

    form.Show()
    return form


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as e:
        print("[steel_estimate_rhino_panel] " + str(e))
        raise SystemExit(1)
