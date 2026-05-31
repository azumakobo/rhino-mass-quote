"""公開版: rhino_objects.csv から公開参考単価だけで見積一式を作る（estimate-public-rhino）。

実データ・実単価DBを一切使わず、public_reference_data の匿名化・集約・10円切り上げ済み
参考価格のみで動く。元データは上書きしない。
"""

from __future__ import annotations

import os

from . import csv_utils as cu
from . import rhino_csv
from . import layer_summary as lsum
from . import layer_mapping as lmap
from . import enrich
from . import layer_estimate as lest
from . import public_data as pub
from . import settings as tx


DEFAULT_PUBLIC_DIR = "./public_reference_data"
PLATE_NAME = "public_plate_reference_prices.csv"
SHAPE_NAME = "public_shape_reference_prices.csv"


def _resolve_public(public_dir, plate_path, shape_path):
    """公開参考CSVのパスを決める。明示指定 > public_dir > samples フォールバック。"""
    plate = plate_path or os.path.join(public_dir or DEFAULT_PUBLIC_DIR, PLATE_NAME)
    shape = shape_path or os.path.join(public_dir or DEFAULT_PUBLIC_DIR, SHAPE_NAME)
    if not (os.path.exists(plate) and os.path.exists(shape)):
        alt = "./samples/reference_prices"
        if os.path.exists(os.path.join(alt, PLATE_NAME)):
            plate = os.path.join(alt, PLATE_NAME)
            shape = os.path.join(alt, SHAPE_NAME)
    return plate, shape


def estimate_public_rhino(rhino_csv_path: str, out_dir: str,
                          tax_rate: float = tx.DEFAULT_TAX_RATE,
                          public_dir: str = DEFAULT_PUBLIC_DIR,
                          plate_path: str = "", shape_path: str = "",
                          now_str: str = "") -> dict:
    """公開参考単価のみで見積を一括生成し、出力ファイル群と統計を返す。"""
    os.makedirs(out_dir, exist_ok=True)
    plate_csv, shape_csv = _resolve_public(public_dir, plate_path, shape_path)
    if not (os.path.exists(plate_csv) and os.path.exists(shape_csv)):
        raise FileNotFoundError(
            f"公開参考単価が見つかりません: {plate_csv} / {shape_csv}。"
            "build-public-reference-prices を先に実行してください。")

    plate_range = pub.public_plate_to_range(cu.read_dicts(plate_csv))
    shape_range = pub.public_shape_to_range(cu.read_dicts(shape_csv))

    # 1. Rhino CSV → レイヤー集計
    objs = rhino_csv.read_rhino_objects(rhino_csv_path)
    summary = lsum.build_summary(objs)
    lsum.write_summary(os.path.join(out_dir, "layer_summary.csv"), summary)

    # 2. 初期 mapping（自動推定の雛形）
    mapping_initial = lmap.init_mapping_from_summary(summary)
    lmap.write_mapping(os.path.join(out_dir, "layer_mapping_initial.csv"), mapping_initial)

    # 3. 公開参考単価で補完（元は非上書き・別ファイル）
    enriched = enrich.enrich_mapping(
        mapping_initial, summary, [], tax_rate=tax_rate,
        plate_range_rows=plate_range, shape_range_rows=shape_range)
    lmap.write_mapping(os.path.join(out_dir, "layer_mapping_enriched.csv"), enriched)

    # 4. 見積
    results, summ = lest.estimate_layers(summary, enriched, tax_rate=tax_rate)
    lest.write_results(os.path.join(out_dir, "estimate_result.csv"), results)
    lest.write_summary(os.path.join(out_dir, "estimate_summary.csv"), summ)

    # 5. 何がいくらか
    what = lest.build_what_costs(results, tax_rate)
    lest.write_what_costs(os.path.join(out_dir, "what_costs_how_much.csv"), what)

    # 6. レポート
    stats = _collect_stats(objs, summary, enriched, results, summ, tax_rate)
    report_path = os.path.join(out_dir, "public_rhino_estimate_report.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(_render_report(rhino_csv_path, plate_csv, shape_csv, stats, what, now_str))

    return {
        "out_dir": out_dir,
        "report_path": report_path,
        "plate_csv": plate_csv,
        "shape_csv": shape_csv,
        "stats": stats,
        "what": what,
        "summary_rows": summ,
    }


def _collect_stats(objs, summary, enriched, results, summ, tax_rate) -> dict:
    enr_by = {r.get("layer_name", ""): r for r in enriched}
    matched, unmatched = [], []
    for r in enriched:
        calc = (r.get("calc_type", "") or "").strip()
        if calc in ("", "ignore", "fixed_amount", "object_count", "manual_quantity"):
            continue
        if (r.get("price_range_source") or "").strip():
            matched.append(r.get("layer_name", ""))
        else:
            unmatched.append(r.get("layer_name", ""))

    ignored = [r["layer_name"] for r in results if r.get("_summary_category") == "ignored"]
    target = [r.get("layer_name", "") for r in enriched
              if (r.get("calc_type", "") or "").strip() not in ("", "ignore")]
    review = sum(1 for r in results if str(r.get("needs_review")) == "true")
    warns = sum(1 for r in results if (r.get("warning") or "").strip())

    total = next((s for s in summ if str(s["category"]).startswith("TOTAL")), {})
    return {
        "objects": sum(int(cu.to_float(s.get("object_count")) or 0) for s in summary),
        "layers": len(summary),
        "target_layers": target,
        "ignored_layers": ignored,
        "matched_layers": matched,
        "unmatched_layers": unmatched,
        "needs_review": review,
        "warnings": warns,
        "tax_rate": tx.normalize_rate(tax_rate),
        "subtotal_ex_tax": total.get("subtotal_amount_ex_tax", 0),
        "tax_amount": total.get("tax_amount", 0),
        "subtotal_inc_tax": total.get("subtotal_amount_inc_tax", 0),
        "recommended_ex_tax": total.get("recommended_subtotal_ex_tax", 0),
        "recommended_inc_tax": total.get("recommended_subtotal_inc_tax", 0),
        "conservative_ex_tax": total.get("conservative_subtotal_ex_tax", 0),
        "conservative_inc_tax": total.get("conservative_subtotal_inc_tax", 0),
    }


def _render_report(rhino_csv_path, plate_csv, shape_csv, s, what, now_str) -> str:
    L = [
        "# 公開版 Rhinoレイヤー見積レポート",
        "",
        f"- 実行日時: {now_str or '(未記録)'}",
        f"- 入力CSV: `{rhino_csv_path}`",
        f"- 公開参考単価: `{plate_csv}` / `{shape_csv}`",
        "- **公開用参考価格（匿名化・集約・10円単位切上げ済）。実取引価格ではありません。**",
        "",
        "## 集計",
        f"- オブジェクト数: {s['objects']} / レイヤー数: {s['layers']}",
        f"- 見積対象レイヤー: {len(s['target_layers'])} / 見積対象外(ignore等): {len(s['ignored_layers'])}",
        f"- 参考単価がmatchしたレイヤー: {len(s['matched_layers'])}",
        f"- matchしなかったレイヤー: {len(s['unmatched_layers'])}",
        f"- needs_review: {s['needs_review']} / warning: {s['warnings']}",
        "",
        "## 合計金額",
        f"- 税抜合計: ¥{s['subtotal_ex_tax']:,}",
        f"- 消費税({s['tax_rate']*100:g}%): ¥{s['tax_amount']:,}",
        f"- 税込合計: ¥{s['subtotal_inc_tax']:,}",
        f"- recommended(中央値相当) 税抜¥{s['recommended_ex_tax']:,} / 税込¥{s['recommended_inc_tax']:,}",
        f"- conservative(最大値相当) 税抜¥{s['conservative_ex_tax']:,} / 税込¥{s['conservative_inc_tax']:,}",
        "",
        "## 何がいくらか",
        "| レイヤー/品目 | カテゴリ | 数量 | 単価(税抜) | 税込金額 |",
        "|---|---|---|--:|--:|",
    ]
    for w in what:
        amt_inc = w.get("estimated_amount_inc_tax", "")
        up = w.get("unit_price_ex_tax", "")
        L.append(f"| {w.get('layer_name') or w.get('item_name')} | {w.get('material_category')} | "
                 f"{w.get('basis_quantity')}{w.get('basis_unit')} | "
                 f"¥{up}/{w.get('price_unit')} | ¥{amt_inc} |")
    L += ["", "## matchしなかった見積対象レイヤー（要確認）"]
    L += ([f"- {n}" for n in s["unmatched_layers"]] or ["- なし"])
    L += [
        "",
        "## 人間が確認すべき項目",
        "- match単価は参考値。実発注前に必ず実見積で確認する。",
        "- 加工費（曲げ・切断・溶接・塗装・運搬）は材料費と分離（cost_items / fixed_amount）。",
        "- matchしなかったレイヤーは mapping UI で単価/pricing_mode/manual_unit_price を設定する。",
        "",
        "## Rhino作図上の注意",
        "- パイプ・アングル類は中心線カーブで作る（長さ集計のため）。",
        "- 板材は閉じた平面曲線かサーフェスで作る（面積取得のため）。",
        "- ブロック(InstanceObject)は未展開。内部数量は集計されない。",
        "",
        "## 次にUIで修正すべき項目",
        "- 単価未設定/unmatchedレイヤー、recommended↔conservativeの選択、manual単価の入力。",
        "",
        "> 本見積は概算です。公開用参考価格に基づくため、最終発注前に必ず確認してください。",
    ]
    return "\n".join(L) + "\n"
