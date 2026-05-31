"""run-rhino-estimate: rhino_objects.csv から見積一式までを一括実行する。

フロー: validate → summarize-layers → (既存があれば)update / (無ければ)init mapping
        → estimate-by-layer → estimate_summary → rhino_estimate_report.md

原則:
  - 既存 mapping は絶対に上書きしない（新規レイヤーだけ追加した updated を別ファイルに出す）。
  - 見積不能項目があっても止めず needs_review=true で出す。
  - 必須ヘッダー不足など CSV として処理不能な場合のみ停止する。
"""

from __future__ import annotations

import os

from . import csv_utils as cu
from . import rhino_csv
from . import layer_summary as lsum
from . import layer_mapping as lmap
from . import cost_items as citems
from . import layer_estimate as lest
from . import settings as tx


class RhinoEstimateError(Exception):
    """CSVとして処理不能（必須ヘッダー不足等）。"""


def run_rhino_estimate(rhino_csv_path: str, mapping_path: str | None,
                       cost_items_path: str | None, out_dir: str,
                       db_path: str | None = None, manual_prices_path: str | None = None,
                       now_str: str = "", tax_rate: float = tx.DEFAULT_TAX_RATE) -> dict:
    rate = tx.normalize_rate(tax_rate)
    os.makedirs(out_dir, exist_ok=True)

    # 1. validate（必須ヘッダー不足のみ停止）
    report = rhino_csv.validate_rhino_csv(rhino_csv_path)
    header_err = [e for e in report["errors"] if "必須ヘッダー" in e]
    if header_err:
        raise RhinoEstimateError("; ".join(header_err))

    # 2. summarize-layers
    objs = rhino_csv.read_rhino_objects(rhino_csv_path)
    summary_rows = lsum.build_summary(objs)
    summary_path = os.path.join(out_dir, "layer_summary.csv")
    lsum.write_summary(summary_path, summary_rows)

    # 3/4. mapping（既存は保持し新規だけ追加。なければ雛形生成）
    if mapping_path and os.path.exists(mapping_path):
        existing = lmap.read_mapping(mapping_path)
        merged, added = lmap.update_mapping(existing, summary_rows)
        mapping_out = os.path.join(out_dir, "layer_mapping_updated.csv")
        mapping_mode = "updated"
    else:
        merged = lmap.init_mapping_from_summary(summary_rows)
        added = [r["layer_name"] for r in merged]
        mapping_out = os.path.join(out_dir, "layer_mapping.csv")
        mapping_mode = "init"
    lmap.write_mapping(mapping_out, merged)

    # 5. estimate-by-layer
    cost_rows = citems.read_cost_items(cost_items_path) if cost_items_path else None
    manual_prices = cu.read_dicts(manual_prices_path) if manual_prices_path else None
    from . import database as db
    conn = db.connect(db_path) if db_path else None
    results, summ = lest.estimate_layers(
        summary_rows, merged, cost_rows=cost_rows, db_conn=conn,
        manual_prices=manual_prices, tax_rate=rate)
    if conn:
        conn.close()

    result_path = os.path.join(out_dir, "estimate_result.csv")
    summary_out = os.path.join(out_dir, "estimate_summary.csv")
    lest.write_results(result_path, results)
    lest.write_summary(summary_out, summ)

    # ユーザーが最初に見る『何がいくらか』（税込を見やすく、税抜・税額も併記）
    what_costs = lest.build_what_costs(results, rate)
    what_costs_path = os.path.join(out_dir, "what_costs_how_much.csv")
    lest.write_what_costs(what_costs_path, what_costs)

    # 6/7. レポート用の集計
    stats = _collect_stats(summary_rows, results, summ, added)
    candidate_hints = _candidate_hints(out_dir)
    report_path = os.path.join(out_dir, "rhino_estimate_report.md")
    md = _render_report(
        now_str=now_str, rhino_csv_path=rhino_csv_path, mapping_out=mapping_out,
        mapping_mode=mapping_mode, validate_report=report, stats=stats, category_rows=summ,
        candidate_hints=candidate_hints, tax_rate=rate)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(md)

    return {
        "summary_path": summary_path,
        "mapping_out": mapping_out,
        "mapping_mode": mapping_mode,
        "result_path": result_path,
        "summary_out": summary_out,
        "what_costs_path": what_costs_path,
        "report_path": report_path,
        "added_layers": added,
        "stats": stats,
        "category_rows": summ,
    }


def _collect_stats(summary_rows, results, summ, added) -> dict:
    layer_results = [r for r in results if r["source_type"] in ("rhino_layer", "ignored")]
    review = [r for r in results if str(r.get("needs_review")) == "true"]
    warns = [r for r in results if (r.get("warning") or "").strip()]
    unmapped = [r for r in layer_results
                if str(r.get("needs_review")) == "true" and r["accuracy_level"] == "unknown"]
    total_row = next((s for s in summ if s["category"].startswith("TOTAL")), None)
    return {
        "objects": sum(int(cu.to_float(s.get("object_count")) or 0) for s in summary_rows),
        "layers": len(summary_rows),
        "area_layers": sum(1 for s in summary_rows if (cu.to_float(s.get("total_area_m2")) or 0) > 0),
        "curve_layers": sum(1 for s in summary_rows if (cu.to_float(s.get("total_curve_length_m")) or 0) > 0),
        "volume_layers": sum(1 for s in summary_rows if (cu.to_float(s.get("total_volume_mm3")) or 0) > 0),
        "mapped_ok": sum(1 for r in layer_results
                         if str(r.get("needs_review")) == "false" and r["accuracy_level"] != "ignored"),
        "unmapped": len(unmapped),
        "needs_review": len(review),
        "warnings": len(warns),
        "estimated_total": total_row["subtotal_amount"] if total_row else 0,
        "estimated_total_ex_tax": (total_row.get("subtotal_amount_ex_tax") if total_row else 0) or 0,
        "estimated_tax": (total_row.get("tax_amount") if total_row else 0) or 0,
        "estimated_total_inc_tax": (total_row.get("subtotal_amount_inc_tax") if total_row else 0) or 0,
        "unmapped_names": [r["layer_name"] for r in unmapped],
        "warning_examples": [f"[{r['layer_name'] or r['item_name']}] {r['warning']}" for r in warns][:8],
        "newly_added": added,
    }


def _candidate_hints(out_dir: str) -> list[str]:
    """候補単価CSVが存在すれば、レポート用の案内行を返す（R4統合）。"""
    hints: list[str] = []
    summary_csv = os.path.join(out_dir, "toko_candidate_price_summary.csv")
    sugg_csv = os.path.join(out_dir, "layer_mapping_price_suggestions.csv")
    if os.path.exists(summary_csv):
        hints.append("候補単価マスター `toko_candidate_price_summary.csv` があります。"
                     "単価未設定レイヤーは `suggest-prices-for-mapping` を実行してください。")
    if os.path.exists(sugg_csv):
        try:
            rows = cu.read_dicts(sugg_csv)
            counts = {"exact": 0, "close": 0, "category_only": 0, "none": 0}
            for r in rows:
                lv = r.get("match_level", "none")
                counts[lv] = counts.get(lv, 0) + 1
            hints.append(
                f"候補単価の提案 `layer_mapping_price_suggestions.csv`: "
                f"exact {counts['exact']} / close {counts['close']} / "
                f"category_only {counts['category_only']} / none {counts['none']}")
        except Exception:
            pass
    return hints


def _render_report(now_str, rhino_csv_path, mapping_out, mapping_mode,
                   validate_report, stats, category_rows, candidate_hints=None,
                   tax_rate=tx.DEFAULT_TAX_RATE) -> str:
    s = stats
    rate = tx.normalize_rate(tax_rate)
    lines = [
        "# Rhinoレイヤー見積 実行レポート",
        "",
        f"- 実行日時: {now_str or '(未記録)'}",
        f"- 入力CSV: `{rhino_csv_path}`",
        f"- mapping: `{mapping_out}`（{'既存を保持し新規追加' if mapping_mode == 'updated' else '新規雛形を生成'}）",
        "",
        "## 集計",
        f"- オブジェクト数: {s['objects']}",
        f"- レイヤー数: {s['layers']}",
        f"- 面積取得レイヤー数: {s['area_layers']}",
        f"- 曲線長取得レイヤー数: {s['curve_layers']}",
        f"- 体積取得レイヤー数: {s['volume_layers']}",
        f"- 見積確定レイヤー数: {s['mapped_ok']}",
        f"- mapping未設定（要対応）レイヤー数: {s['unmapped']}",
        f"- needs_review件数: {s['needs_review']}",
        f"- warning件数: {s['warnings']}",
        "",
        f"## 概算合計（ignored除く・税率{rate:.0%}）",
        f"- 税抜合計: ¥{int(s['estimated_total_ex_tax']):,}",
        f"- 消費税額: ¥{int(s['estimated_tax']):,}",
        f"- **税込合計: ¥{int(s['estimated_total_inc_tax']):,}**",
        "",
        "## カテゴリ別小計（税抜 / 消費税 / 税込）",
        "| カテゴリ | 税抜小計 | 消費税 | 税込小計 | 件数 | needs_review | warning |",
        "|---|--:|--:|--:|--:|--:|--:|",
    ]
    for c in category_rows:
        lines.append(
            f"| {c['category']} | ¥{int(c.get('subtotal_amount_ex_tax') or 0):,} | "
            f"¥{int(c.get('tax_amount') or 0):,} | ¥{int(c.get('subtotal_amount_inc_tax') or 0):,} | "
            f"{c['item_count']} | {c['needs_review_count']} | {c['warning_count']} |")
    lines.append("")
    # 未設定レイヤー一覧
    lines.append("## mapping未設定（要対応）レイヤー")
    if s["unmapped_names"]:
        for n in s["unmapped_names"]:
            lines.append(f"- {n}")
    else:
        lines.append("- なし")
    lines.append("")
    if s["newly_added"]:
        lines.append("## 今回mappingに新規追加されたレイヤー")
        for n in s["newly_added"]:
            lines.append(f"- {n}")
        lines.append("")
    # warning 代表例
    lines.append("## warning 代表例")
    if s["warning_examples"]:
        for w in s["warning_examples"]:
            lines.append(f"- {w}")
    else:
        lines.append("- なし")
    lines.append("")
    # 候補単価マスター（R4）の案内
    if candidate_hints:
        lines.append("## 候補単価マスター")
        for h in candidate_hints:
            lines.append(f"- {h}")
        lines.append("")
    # validate のエラー/警告
    if validate_report["errors"] or validate_report["warnings"]:
        lines.append("## CSV検証メモ")
        for e in validate_report["errors"]:
            lines.append(f"- ERROR: {e}")
        for w in validate_report["warnings"]:
            lines.append(f"- WARN: {w}")
        lines.append("")
    # 次にユーザーが編集すべきファイル
    lines += [
        "## 次に編集すべきファイル",
        "1. `layer_mapping_updated.csv`（または `layer_mapping.csv`）"
        " — 未設定レイヤーの calc_type / 寸法 / unit_price を確定する",
        "2. `cost_items.csv` — 加工費・運搬費・施工費など（材料費と分離）",
        "3. 編集後にもう一度 `run-rhino-estimate` を実行し `estimate_result.csv` /"
        " `estimate_summary.csv` を確認する",
        "",
        "> 本見積は概算です。最終発注前に必ず人間が確認してください。",
    ]
    return "\n".join(lines) + "\n"
