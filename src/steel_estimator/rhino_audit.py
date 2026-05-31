"""rhino_objects.csv の作図品質監査（audit-rhino-geometry）。

見積精度は Rhino の作図品質に依存するため、見積前に問題を error/warning/info で洗い出す。
見積処理自体は原則止めない（重大なヘッダー不足は validate 側で検出）。
"""

from __future__ import annotations

from . import csv_utils as cu
from .layer_summary import IGNORE_HINTS, PLATE_HINTS


# 極端なサイズの閾値（mm）
TINY_MM = 1.0
HUGE_MM = 50_000.0  # 50m


def _f(r, key):
    return cu.to_float(r.get(key)) or 0.0


def audit_rhino_geometry(path: str) -> dict:
    """監査を実行し、findings と stats を返す。

    finding: {severity, code, title, count, examples[]}
    severity: error / warning / info
    """
    rows = cu.read_dicts(path)
    findings: list[dict] = []

    def add(severity, code, title, items):
        if items:
            findings.append({
                "severity": severity, "code": code, "title": title,
                "count": len(items), "examples": items[:8],
            })

    empty_layer, dup_examples = [], []
    zero_geom, not_closed_area, curve_len0, brep_vol0 = [], [], [], []
    tiny, huge, unit_notes, aux_layers, annotations, blocks = [], [], [], [], [], []

    seen_ids: dict[str, int] = {}
    for i, r in enumerate(rows, start=2):
        layer = (r.get("layer_name") or "").strip()
        name = (r.get("object_name") or "").strip()
        otype = (r.get("object_type") or "").strip()
        notes = (r.get("notes") or "")
        oid = (r.get("object_id") or "").strip()
        area = _f(r, "object_area_mm2")
        vol = _f(r, "object_volume_mm3")
        clen = _f(r, "object_curve_length_mm")
        bbw = _f(r, "bounding_box_width_mm")
        bbh = _f(r, "bounding_box_height_mm")
        bbd = _f(r, "bounding_box_depth_mm")
        is_curve = cu.to_bool(r.get("is_curve"), default=False)
        is_closed_curve = cu.to_bool(r.get("is_closed_curve"), default=False)
        is_closed_brep = cu.to_bool(r.get("is_closed_brep"), default=False)
        tag = f"行{i} [{layer}] {name or otype}"

        if not layer:
            empty_layer.append(f"行{i} id={oid or '(空)'}")
        if oid:
            if oid in seen_ids:
                dup_examples.append(f"{oid} (行{seen_ids[oid]},{i})")
            seen_ids[oid] = i

        if area == 0 and vol == 0 and clen == 0 and otype not in ("Point", "Annotation"):
            zero_geom.append(tag)
        # 板材候補レイヤーなのに開いた曲線で面積0
        if is_curve and not is_closed_curve and area == 0 and \
                any(h.upper() in layer.upper() for h in PLATE_HINTS):
            not_closed_area.append(tag + "（閉じた平面曲線にすると面積が取れる）")
        if is_curve and clen == 0:
            curve_len0.append(tag)
        if is_closed_brep and vol == 0:
            brep_vol0.append(tag + "（閉ソリッドだが体積0：作図/法線を確認）")

        maxdim = max(bbw, bbh, bbd)
        if 0 < maxdim < TINY_MM:
            tiny.append(f"{tag} 最大{maxdim:g}mm")
        if maxdim > HUGE_MM:
            huge.append(f"{tag} 最大{maxdim:g}mm")

        low = notes.lower()
        if "unsupported model unit" in low:
            unit_notes.append(f"{tag}: {notes}")
        elif "converted to mm" in low:
            unit_notes.append(f"{tag}: {notes}")

        if layer and any(h in layer for h in IGNORE_HINTS):
            aux_layers.append(tag)
        if otype == "Annotation" or any(h in (layer + name).lower() for h in ("dim", "text", "注釈", "寸法")):
            annotations.append(tag)
        if otype in ("InstanceObject", "Block"):
            blocks.append(tag + "（block未展開：内部数量は集計されない）")

    # error
    add("error", "empty_layer", "レイヤー名が空のオブジェクト", empty_layer)
    # warning
    add("warning", "duplicate_id", "object_id の重複", dup_examples)
    add("warning", "zero_geometry", "面積・体積・曲線長がすべて0", zero_geom)
    add("warning", "open_curve_area", "板材候補だが開いた曲線（面積取得不可）", not_closed_area)
    add("warning", "curve_len_zero", "曲線長が0のCurve", curve_len0)
    add("warning", "brep_volume_zero", "体積0の閉Brep候補", brep_vol0)
    add("warning", "huge_object", "極端に大きいオブジェクト(>50m)", huge)
    add("warning", "unit_converted", "mm以外からの単位換算/未対応単位", unit_notes)
    # info
    add("info", "tiny_object", "極端に小さいオブジェクト(<1mm)", tiny)
    add("info", "block_instance", "Block(InstanceObject)（v1未展開）", blocks)
    add("info", "annotation", "注釈/寸法/テキスト系オブジェクト", annotations)
    add("info", "aux_layer", "補助線らしいレイヤー（ignore推奨）", aux_layers)

    sev_counts = {"error": 0, "warning": 0, "info": 0}
    for f in findings:
        sev_counts[f["severity"]] += 1

    return {
        "findings": findings,
        "stats": {
            "rows": len(rows),
            "layers": len({(r.get("layer_name") or "") for r in rows}),
            "errors": sev_counts["error"],
            "warnings": sev_counts["warning"],
            "infos": sev_counts["info"],
        },
    }


_SEV_LABEL = {"error": "🔴 ERROR", "warning": "🟡 WARNING", "info": "🔵 INFO"}


def render_markdown(report: dict, input_path: str, now_str: str = "") -> str:
    st = report["stats"]
    lines = [
        "# Rhino作図品質 監査レポート",
        "",
        f"- 入力: `{input_path}`",
    ]
    if now_str:
        lines.append(f"- 実行: {now_str}")
    lines += [
        f"- オブジェクト数: {st['rows']} / レイヤー数: {st['layers']}",
        f"- error: {st['errors']} / warning: {st['warnings']} / info: {st['infos']}",
        "",
        "> 見積処理は原則止めません。error は要修正、warning/info は確認推奨です。",
        "",
    ]
    if not report["findings"]:
        lines.append("問題は検出されませんでした。")
        return "\n".join(lines) + "\n"

    for sev in ("error", "warning", "info"):
        items = [f for f in report["findings"] if f["severity"] == sev]
        if not items:
            continue
        lines.append(f"## {_SEV_LABEL[sev]}")
        for f in items:
            lines.append(f"### {f['title']}（{f['count']}件） `[{f['code']}]`")
            for ex in f["examples"]:
                lines.append(f"- {ex}")
            if f["count"] > len(f["examples"]):
                lines.append(f"- …他 {f['count'] - len(f['examples'])} 件")
            lines.append("")
    return "\n".join(lines) + "\n"


def write_audit_md(report: dict, input_path: str, out_path: str, now_str: str = "") -> str:
    import os
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    md = render_markdown(report, input_path, now_str)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(md)
    return out_path
