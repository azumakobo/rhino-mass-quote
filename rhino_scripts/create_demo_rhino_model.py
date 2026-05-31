"""Rhino 8 ScriptEditor / Python 3 / RhinoCommon 専用スクリプト。

★ 通常の python では動きません（RhinoCommon が必要）。Rhino 8 の `_ScriptEditor` で
   言語を「Python 3 (CPython / RhinoCommon)」にして実行してください。
★ デモ用の新規ドキュメントで実行することを推奨（既存オブジェクトは消しません）。

実行すると、見積パイプラインのテストに使えるレイヤーと簡単な形状を現在の
ドキュメントに作成する。これは**公開用の合成モデル**であり、実案件データではない。

レイヤー命名は steel-estimator の自動推定が解釈できる ASCII コード規約に従う:
  <CODE>_<GRADE>_<dims>   例) PL_SS400_t6, SQPIPE_STKR_100x50_t2.3,
  PIPE_STK400_D101.6_t3.2, FB_SS400_50x4.5, ANGLE_SS400_40x40_t3
  BOLT_TEST(購入部品), IGNORE_GUIDE(補助線)

作図後、`rhino_scripts/export_rhino_objects.py` を実行して rhino_objects.csv を出力し、
`estimate-public-rhino` に渡す（docs/rhino-test-procedure.md 参照）。

寸法は public_reference_data の参考価格に一致する規格を選んでいる。
"""

# レイヤー定義: (layer_name, kind, params)
# 簡素化方針(2026-05-31): **これは鋼材形状の再現ではなく、volume_to_weight の動作確認用Box**。
# 各レイヤーに volume が取れる単純な Box/Cylinder を置くだけ（見積は Rhinoの体積 × kg単価）。
# 正確な材料重量が必要な場合は、ユーザーがRhino上で正しい材料体積のポリサーフェスを作る。
# kind: "box"=直方体ソリッド, "cylinder"=円柱ソリッド, "points"=点群, "guide"=補助線
DEMO_LAYERS = [
    # 実運用に近いレイヤー名。中身は単純Boxでよい（体積が取れればよい）。
    # 見積 = レイヤー内volume × 密度 × レイヤー名から引いたkg単価。
    ("PL_SS400_t6", "box", {"w": 1000.0, "h": 500.0, "length": 6.0}),
    ("PL_SS400_t9", "box", {"w": 1000.0, "h": 500.0, "length": 9.0}),
    ("SQPIPE_STKR_40x40_t2.3", "box", {"w": 40.0, "h": 40.0, "length": 6000.0}),
    ("PIPE_STK_D48.6_t2.3", "box", {"w": 48.6, "h": 48.6, "length": 6000.0}),
    ("FB_SS400_50x4.5", "box", {"w": 50.0, "h": 4.5, "length": 3000.0}),
    ("ANGLE_SS400_40x40_t3", "box", {"w": 40.0, "h": 40.0, "length": 3000.0}),
    ("BOLT_TEST", "points", {"count": 6}),
    ("IGNORE_GUIDE", "guide", {"length": 2000.0}),
]


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
    _require_rhino()
    import scriptcontext as sc
    import Rhino

    doc = sc.doc
    G = Rhino.Geometry
    created = []
    y = 0.0  # レイヤーごとに y をずらして重ならないように配置

    for name, kind, p in DEMO_LAYERS:
        layer_index = _ensure_layer(doc, name)
        attr = Rhino.DocObjects.ObjectAttributes()
        attr.LayerIndex = layer_index

        try:
            if kind == "box":
                w, h, length = p["w"], p["h"], p["length"]
                box = G.Box(G.BoundingBox(G.Point3d(0, y, 0), G.Point3d(w, y + h, length)))
                doc.Objects.AddBrep(box.ToBrep(), attr)
                y += h + 500.0
            elif kind == "cylinder":
                r = p["d"] / 2.0
                base = G.Plane(G.Point3d(r, y + r, 0), G.Vector3d(0, 0, 1))
                cyl = G.Cylinder(G.Circle(base, r), p["length"])
                doc.Objects.AddBrep(cyl.ToBrep(True, True), attr)
                y += p["d"] + 500.0
            elif kind == "rect":
                w, h = p["w"], p["h"]
                pts = [G.Point3d(0, y, 0), G.Point3d(w, y, 0),
                       G.Point3d(w, y + h, 0), G.Point3d(0, y + h, 0), G.Point3d(0, y, 0)]
                doc.Objects.AddCurve(G.Polyline(pts).ToNurbsCurve(), attr)
                y += h + 500.0
            elif kind == "guide":
                doc.Objects.AddLine(G.Line(G.Point3d(0, y, 0), G.Point3d(p["length"], y, 0)), attr)
                y += 500.0
            elif kind == "points":
                for i in range(p["count"]):
                    doc.Objects.AddPoint(G.Point3d(i * 100.0, y, 0), attr)
                y += 500.0
            created.append(name)
        except Exception as e:
            try:
                Rhino.RhinoApp.WriteLine("  [WARN] %s の作図に失敗: %s" % (name, e))
            except Exception:
                pass

    # 単位が mm でない場合の注意
    unit_note = ""
    try:
        if str(doc.ModelUnitSystem) != "Millimeters":
            unit_note = ("\n注意: モデル単位が %s です。export時に mm 換算されますが、"
                         "デモは mm 前提です。" % doc.ModelUnitSystem)
    except Exception:
        pass

    # Zoom Extents（全ビュー）。失敗しても無視。
    try:
        for view in doc.Views:
            view.ActiveViewport.ZoomExtents()
        doc.Views.Redraw()
    except Exception:
        try:
            doc.Views.Redraw()
        except Exception:
            pass

    msg = ("=== create_demo_rhino_model 完了 ===\n"
           "※ 中身は単純Boxでよい。見積はレイヤー内volumeを材料量として扱い、\n"
           "   レイヤー名から推定したkg単価を掛けます（断面形状の再現は不要）。\n"
           "作成レイヤー: %d\n  %s%s\n"
           "次の手順:\n"
           "  - Rhino内UI: steel_estimate_rhino_panel.py を Run（レイヤー別の金額を確認）\n"
           "  - またはCLI: export_rhino_objects.py → estimate-public-rhino"
           % (len(created), ", ".join(created), unit_note))
    try:
        Rhino.RhinoApp.WriteLine(msg)
    except Exception:
        pass
    try:
        import rhinoscriptsyntax as rs
        rs.MessageBox(msg, 0, "create_demo_rhino_model")
    except Exception:
        pass
    print(msg)
    return created


def _rect_curve(G, x0, y0, w, h):
    """XY平面の閉じた矩形 NurbsCurve。"""
    pts = [G.Point3d(x0, y0, 0), G.Point3d(x0 + w, y0, 0),
           G.Point3d(x0 + w, y0 + h, 0), G.Point3d(x0, y0 + h, 0), G.Point3d(x0, y0, 0)]
    return G.Polyline(pts).ToNurbsCurve()


def _add_extrusion(doc, G, attr, outer_curve, length, inner_curve):
    """閉じた平面プロファイルを +Z に押し出してキャップした閉ソリッド(Brep)を追加する。

    inner_curve があれば中空（角パイプ・丸パイプ）。体積が取得できる。
    """
    ext = G.Extrusion.Create(outer_curve, length, True)  # cap=True で閉ソリッド
    if ext is None:
        raise RuntimeError("Extrusion.Create が None を返した（プロファイルが閉/平面か確認）")
    if inner_curve is not None:
        ext.AddInnerProfile(inner_curve)
    brep = ext.ToBrep(True)
    if brep is None or not brep.IsValid:
        # フォールバック: Extrusion のまま追加（体積はRhino側で計算可）
        doc.Objects.AddExtrusion(ext, attr)
        return
    doc.Objects.AddBrep(brep, attr)


def _ensure_layer(doc, name):
    """フルパス name のレイヤーを取得（無ければ作成）してインデックスを返す。"""
    import Rhino
    existing = doc.Layers.FindName(name) if hasattr(doc.Layers, "FindName") else None
    if existing is not None:
        return existing.Index
    # 旧API互換
    idx = doc.Layers.Find(name, True) if hasattr(doc.Layers, "Find") else -1
    if idx is not None and idx >= 0:
        return idx
    layer = Rhino.DocObjects.Layer()
    layer.Name = name
    return doc.Layers.Add(layer)


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as e:
        print("[create_demo_rhino_model] " + str(e))
        raise SystemExit(1)
