"""RhinoエクスポートCSV（rhino_objects.csv）の読み込み。

将来 RhinoCommon / rhino3dm 連携に置き換える前段として、
Rhinoから出力された CSV を入力に取る。スキーマは設計書 §1 を参照。
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Optional

from . import csv_utils as cu


RHINO_OBJECT_FIELDS = (
    "file_name",
    "layer_name",
    "object_id",
    "object_name",
    "object_type",
    "object_count",
    "object_area_mm2",
    "object_volume_mm3",
    "object_curve_length_mm",
    "bounding_box_width_mm",
    "bounding_box_height_mm",
    "bounding_box_depth_mm",
    "is_closed_curve",
    "is_closed_brep",
    "is_surface",
    "is_mesh",
    "is_curve",
    "notes",
)

_FLOAT_FIELDS = {
    "object_area_mm2", "object_volume_mm3", "object_curve_length_mm",
    "bounding_box_width_mm", "bounding_box_height_mm", "bounding_box_depth_mm",
}
_INT_FIELDS = {"object_count"}
_BOOL_FIELDS = {"is_closed_curve", "is_closed_brep", "is_surface", "is_mesh", "is_curve"}


@dataclass
class RhinoObject:
    file_name: str = ""
    layer_name: str = ""
    object_id: str = ""
    object_name: str = ""
    object_type: str = ""
    object_count: int = 1
    object_area_mm2: Optional[float] = None
    object_volume_mm3: Optional[float] = None
    object_curve_length_mm: Optional[float] = None
    bounding_box_width_mm: Optional[float] = None
    bounding_box_height_mm: Optional[float] = None
    bounding_box_depth_mm: Optional[float] = None
    is_closed_curve: bool = False
    is_closed_brep: bool = False
    is_surface: bool = False
    is_mesh: bool = False
    is_curve: bool = False
    notes: str = ""

    @classmethod
    def from_row(cls, row: dict) -> "RhinoObject":
        kwargs = {}
        for f in fields(cls):
            raw = row.get(f.name, "")
            if f.name in _FLOAT_FIELDS:
                kwargs[f.name] = cu.to_float(raw)
            elif f.name in _INT_FIELDS:
                v = cu.to_int(raw)
                kwargs[f.name] = v if v is not None else 1
            elif f.name in _BOOL_FIELDS:
                kwargs[f.name] = cu.to_bool(raw, default=False)
            else:
                kwargs[f.name] = (str(raw).strip() if raw is not None else "")
        return cls(**kwargs)


def read_rhino_objects(path: str) -> list[RhinoObject]:
    """rhino_objects.csv を RhinoObject のリストとして読む。

    日本語・スペース・記号を含む layer_name もそのまま保持する。
    """
    rows = cu.read_dicts(path)
    return [RhinoObject.from_row(r) for r in rows]


# ============================================================
# 単位換算（Rhino非依存。エクスポートスクリプトと共通仕様）
# ============================================================

# モデル単位名 → mm への換算係数
UNIT_SCALE_TO_MM = {
    "millimeters": 1.0, "millimeter": 1.0, "mm": 1.0,
    "centimeters": 10.0, "centimeter": 10.0, "cm": 10.0,
    "meters": 1000.0, "meter": 1000.0, "m": 1000.0,
    "inches": 25.4, "inch": 25.4, "in": 25.4,
    "feet": 304.8, "foot": 304.8, "ft": 304.8,
}


def unit_scale_to_mm(unit_name: str) -> tuple[float, str]:
    """単位名から (mm換算係数, warning)。未対応は (1.0, warning)。"""
    key = (unit_name or "").strip().lower()
    if key in UNIT_SCALE_TO_MM:
        return UNIT_SCALE_TO_MM[key], ""
    return 1.0, f"未対応のモデル単位 '{unit_name}'。mm換算せず scale=1 で出力。"


# ============================================================
# 検証（validate-rhino-csv）
# ============================================================

_NUMERIC_COLS = (
    "object_count", "object_area_mm2", "object_volume_mm3", "object_curve_length_mm",
    "bounding_box_width_mm", "bounding_box_height_mm", "bounding_box_depth_mm",
)
_ZERO_GEOM_WARN_RATIO = 0.6  # 形状量が全て0の行がこの比率を超えたら warning


def validate_rhino_csv(path: str) -> dict:
    """rhino_objects.csv を検証し、レポート dict を返す。

    戻り: {ok, errors[], warnings[], stats{}}。
    エラーで例外は投げず、問題は errors/warnings に積む（後段で止めない方針）。
    """
    errors: list[str] = []
    warnings: list[str] = []
    rows = cu.read_dicts(path)

    # ヘッダー確認（先頭行のキー集合で判定）
    header = set(rows[0].keys()) if rows else set()
    missing = [h for h in RHINO_OBJECT_FIELDS if h not in header]
    if missing:
        errors.append(f"必須ヘッダー欠落: {', '.join(missing)}")

    n = len(rows)
    empty_layer = []
    bad_numeric = []
    ids: dict[str, int] = {}
    dup_ids = set()
    zero_geom = 0
    area_cnt = vol_cnt = curve_cnt = 0

    for i, r in enumerate(rows, start=2):  # 2 = ヘッダー次の行
        if not (r.get("layer_name") or "").strip():
            empty_layer.append(i)
        for col in _NUMERIC_COLS:
            raw = (r.get(col) or "").strip()
            if raw != "" and cu.to_float(raw) is None:
                bad_numeric.append(f"行{i} {col}='{raw}'")
        oid = (r.get("object_id") or "").strip()
        if oid:
            if oid in ids:
                dup_ids.add(oid)
            ids[oid] = ids.get(oid, 0) + 1

        area = cu.to_float(r.get("object_area_mm2")) or 0.0
        vol = cu.to_float(r.get("object_volume_mm3")) or 0.0
        clen = cu.to_float(r.get("object_curve_length_mm")) or 0.0
        if area > 0:
            area_cnt += 1
        if vol > 0:
            vol_cnt += 1
        if clen > 0:
            curve_cnt += 1
        if area == 0 and vol == 0 and clen == 0:
            zero_geom += 1

    if empty_layer:
        errors.append(f"layer_name が空の行: {len(empty_layer)}件 (行 {empty_layer[:10]})")
    if bad_numeric:
        errors.append(f"数値として読めない値: {len(bad_numeric)}件 ({'; '.join(bad_numeric[:8])})")
    if dup_ids:
        warnings.append(f"object_id 重複: {len(dup_ids)}件 ({list(dup_ids)[:5]})")
    if n and zero_geom / n > _ZERO_GEOM_WARN_RATIO:
        warnings.append(
            f"面積/長さ/体積がすべて0の行が多い: {zero_geom}/{n}件。"
            "個数/固定費以外にこの状態が多い場合は作図/単位を確認してください。")

    ok = not errors
    return {
        "ok": ok,
        "errors": errors,
        "warnings": warnings,
        "stats": {
            "rows": n,
            "layers": len({(r.get("layer_name") or "") for r in rows}),
            "with_area": area_cnt,
            "with_volume": vol_cnt,
            "with_curve_length": curve_cnt,
            "zero_geometry": zero_geom,
            "with_notes": sum(1 for r in rows if (r.get("notes") or "").strip()),
        },
    }


# ============================================================
# 期待CSVと実機CSVの差分（compare-rhino-csv）
# ============================================================

def compare_rhino_csv(expected_path: str, actual_path: str) -> dict:
    """期待CSV（samples）と実機CSVを比較し、差分レポート用 dict を返す。"""
    exp = {r.get("layer_name", ""): r for r in cu.read_dicts(expected_path)}
    act = {r.get("layer_name", ""): r for r in cu.read_dicts(actual_path)}
    exp_layers, act_layers = set(exp), set(act)

    rows = []
    for name in sorted(exp_layers | act_layers):
        e, a = exp.get(name), act.get(name)
        issues = []
        if e is None:
            issues.append("期待に無いレイヤー(実機のみ)")
        elif a is None:
            issues.append("実機に無いレイヤー(未出力)")
        else:
            # 面積/曲線長の取得有無を比較（0/空 → 取得失敗の可能性）
            for col, label in (("object_area_mm2", "面積"), ("object_curve_length_mm", "曲線長")):
                ev = cu.to_float(e.get(col)) or 0.0
                av = cu.to_float(a.get(col)) or 0.0
                if ev > 0 and av <= 0:
                    issues.append(f"{label}が実機で0（作図/取得を確認）")
            if (e.get("object_type") or "") != (a.get("object_type") or ""):
                issues.append(f"object_type相違 期待={e.get('object_type')} 実機={a.get('object_type')}")
            if "error" in (a.get("notes") or "").lower() or "failed" in (a.get("notes") or "").lower():
                issues.append(f"notesにエラー: {a.get('notes')}")
        rows.append({"layer_name": name, "in_expected": e is not None,
                     "in_actual": a is not None, "issues": issues})

    return {
        "expected_layers": sorted(exp_layers),
        "actual_layers": sorted(act_layers),
        "missing_in_actual": sorted(exp_layers - act_layers),
        "extra_in_actual": sorted(act_layers - exp_layers),
        "rows": rows,
        "ok": all(not r["issues"] for r in rows),
    }


def render_compare_md(rep: dict, expected_path: str, actual_path: str, now_str: str = "") -> str:
    L = ["# Rhino CSV 差分レポート（期待 vs 実機）", ""]
    if now_str:
        L.append(f"- 実行: {now_str}")
    L += [f"- 期待: `{expected_path}`", f"- 実機: `{actual_path}`",
          f"- 総合: {'✅ 一致（重大差分なし）' if rep['ok'] else '⚠ 差分あり'}",
          f"- 期待レイヤー {len(rep['expected_layers'])} / 実機レイヤー {len(rep['actual_layers'])}",
          ""]
    if rep["missing_in_actual"]:
        L.append("## 実機に出力されなかったレイヤー")
        L += [f"- {n}" for n in rep["missing_in_actual"]] + [""]
    if rep["extra_in_actual"]:
        L.append("## 実機にのみ存在するレイヤー")
        L += [f"- {n}" for n in rep["extra_in_actual"]] + [""]
    L += ["## レイヤー別チェック", "| レイヤー | 期待 | 実機 | 問題 |", "|---|:--:|:--:|---|"]
    for r in rep["rows"]:
        L.append(f"| {r['layer_name']} | {'○' if r['in_expected'] else '-'} | "
                 f"{'○' if r['in_actual'] else '-'} | {'; '.join(r['issues']) or 'OK'} |")
    L += ["", "> 公開用参考価格は概算用。実取引価格ではありません。"]
    return "\n".join(L) + "\n"
