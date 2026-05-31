"""コマンドラインインターフェース。

PDF解析系（既存）:
  ingest          PDF群を解析し CSV または SQLite に保存
  export-review   SQLite からレビュー用CSVを出力
  estimate        material_request.csv から概算見積を作成

Rhinoレイヤー見積系（追加）:
  summarize-layers     rhino_objects.csv → layer_summary.csv
  init-layer-mapping   layer_summary.csv → layer_mapping.csv 雛形
  update-layer-mapping 既存mappingを壊さず新規レイヤーだけ追記
  estimate-by-layer    layer_mapping を正として概算見積を作成
  init-samples         サンプルCSV/ガイドを生成
  suggest-layer        レイヤー名の自動推定だけ確認
  validate-rhino-csv   rhino_objects.csv の妥当性検証
  audit-rhino-geometry rhino_objects.csv の作図品質監査
  run-rhino-estimate   検証→集計→mapping→見積→レポートを一括実行
  build-candidate-prices    PDF単価DB→候補単価マスター（生材/加工品を分離）
  suggest-prices-for-mapping mappingへ候補単価を提案（自動反映しない）
  mapping-ui                候補単価選択UI（ローカルWeb）を起動
  estimate-public-rhino     rhino_objects.csvを公開参考単価だけで一括見積
  compare-rhino-csv         期待CSVと実機CSVの差分レポート
  release-audit             公開前監査（実データ混入/デモ/Rhino/README確認）
"""

from __future__ import annotations

import argparse
import csv
import glob
import os
import sys
from collections import Counter

from . import database as db
from . import estimate as est
from . import csv_utils as cu
from . import rhino_csv
from . import layer_summary as lsum
from . import layer_mapping as lmap
from . import cost_items as citems
from . import layer_estimate as lest
from . import samples as samplegen
from .models import MaterialRequest, ESTIMATE_RESULT_FIELDS, REQUEST_FIELDS
from .pdf_extract import extract_records_from_pdf
from .settings import DEFAULT_TAX_RATE


def _now_str() -> str:
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _find_pdfs(pdf_dir: str) -> list[str]:
    pats = ["*.pdf", "*.PDF"]
    files: list[str] = []
    for p in pats:
        files.extend(glob.glob(os.path.join(pdf_dir, "**", p), recursive=True))
    return sorted(set(files))


def cmd_ingest(args: argparse.Namespace) -> int:
    pdfs = _find_pdfs(args.pdf_dir)
    if args.limit:
        pdfs = pdfs[: args.limit]
    if not pdfs:
        print(f"[ingest] PDFが見つかりません: {args.pdf_dir}", file=sys.stderr)
        return 1

    print(f"[ingest] 対象 {len(pdfs)} PDF を解析します...")
    all_records = []
    errors = 0
    for i, path in enumerate(pdfs, 1):
        try:
            recs = extract_records_from_pdf(path)
            all_records.extend(recs)
        except Exception as e:  # noqa: BLE001 - 1件の失敗で全体を止めない
            errors += 1
            print(f"  [ERROR] {os.path.basename(path)}: {e}", file=sys.stderr)
        if i % 50 == 0:
            print(f"  ... {i}/{len(pdfs)}")

    cat_counts = Counter(r.material_category for r in all_records)
    needs_review = sum(1 for r in all_records if r.needs_review)

    if args.out:
        n = db.write_records_csv(all_records, args.out)
        print(f"[ingest] CSV出力: {args.out} ({n}行)")
    if args.db:
        conn = db.connect(args.db)
        ins, skip = db.insert_records(conn, all_records)
        conn.close()
        print(f"[ingest] SQLite保存: {args.db} (新規{ins}, 重複スキップ{skip})")
    if not args.out and not args.db:
        print("[ingest] --out または --db を指定してください", file=sys.stderr)
        return 2

    print("\n=== 解析サマリ ===")
    print(f"PDF数            : {len(pdfs)}  (エラー {errors})")
    print(f"抽出レコード総数  : {len(all_records)}")
    print(f"needs_review     : {needs_review}")
    print("カテゴリ別件数    :")
    for cat, c in cat_counts.most_common():
        print(f"  {cat:<12}: {c}")
    return 0


def cmd_export_review(args: argparse.Namespace) -> int:
    conn = db.connect(args.db)
    n = db.export_review_csv(conn, args.out)
    conn.close()
    print(f"[export-review] {args.out} ({n}行, needs_review優先)")
    return 0


def cmd_estimate(args: argparse.Namespace) -> int:
    conn = db.connect(args.db)
    # カテゴリ別に候補をキャッシュ
    cache: dict[str, list[dict]] = {}

    with open(args.input, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        requests = [MaterialRequest.from_row(row) for row in reader]

    results = []
    for req in requests:
        if req.material_category not in cache:
            cache[req.material_category] = db.fetch_by_category(conn, req.material_category)
        candidates = cache[req.material_category]
        match = est.match_records(req, candidates)

        unit_price = match["unit_price"]
        basis = match["basis"]
        accuracy = match["accuracy_level"]
        warning = match["warning"]

        # exact/close で単価が無い、または unknown のとき重量×kg単価を試行
        if unit_price is None:
            w = est.estimate_weight_kg(req)
            kg_price = _category_kg_price(candidates)
            if w and kg_price:
                unit_price = w * kg_price
                accuracy = "formula"
                basis = f"重量{w:.2f}kg × kg単価{kg_price:.1f}円(過去平均)"
                warning = (warning + "; 重量式は概算").strip("; ")
            else:
                warning = (warning + "; 重量またはkg単価が不足").strip("; ")

        qty = req.quantity or 1
        amount = unit_price * qty if unit_price is not None else None
        amount_ex = _round(amount)
        from . import settings as _tx
        results.append({
            "item_name": req.item_name,
            "requested_spec": _spec_text(req),
            "quantity": qty,
            "estimated_unit_price": _round(unit_price),
            "estimated_amount": amount_ex,
            "estimated_amount_ex_tax": amount_ex,
            "tax_rate": _tx.normalize_rate(args.tax_rate),
            "estimated_tax_amount": _tx.tax_of(amount_ex, args.tax_rate) if amount_ex != "" else "",
            "estimated_amount_inc_tax": _tx.inc_of(amount_ex, args.tax_rate) if amount_ex != "" else "",
            "estimate_basis": basis,
            "accuracy_level": accuracy,
            "matched_source_pdf": match["source_pdf"],
            "matched_vendor": match["vendor"],
            "matched_quote_date": match["quote_date"],
            "warning": warning,
        })

    conn.close()
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=ESTIMATE_RESULT_FIELDS)
        w.writeheader()
        w.writerows(results)

    levels = Counter(r["accuracy_level"] for r in results)
    print(f"[estimate] {args.out} ({len(results)}件)")
    print("精度区分:", dict(levels))
    return 0


def _category_kg_price(candidates: list[dict]) -> float | None:
    """過去レコードから kg単価の平均を推定（重量が算出できる行のみ）。"""
    prices = []
    for c in candidates:
        req = MaterialRequest(
            material_category=c.get("material_category", ""),
            diameter_mm=c.get("diameter_mm"), thickness_mm=c.get("thickness_mm"),
            width_mm=c.get("width_mm"), height_mm=c.get("height_mm"),
            length_mm=c.get("length_mm"), plate_width_mm=c.get("plate_width_mm"),
            plate_height_mm=c.get("plate_height_mm"),
        )
        w = est.estimate_weight_kg(req)
        up = c.get("unit_price")
        if w and up and w > 0:
            prices.append(up / w)
    if not prices:
        return None
    import statistics
    return statistics.fmean(prices)


def _spec_text(req: MaterialRequest) -> str:
    parts = [req.material_grade]
    for k in ("diameter_mm", "width_mm", "height_mm", "thickness_mm",
              "length_mm", "plate_width_mm", "plate_height_mm"):
        v = getattr(req, k)
        if v is not None:
            parts.append(f"{k.replace('_mm','')}={v:g}")
    return " ".join(p for p in parts if p)


def _round(v):
    return round(v) if isinstance(v, (int, float)) else ""


# ============================================================
# Rhinoレイヤー見積系コマンド
# ============================================================

def cmd_summarize_layers(args: argparse.Namespace) -> int:
    objs = rhino_csv.read_rhino_objects(args.input)
    rows = lsum.build_summary(objs)
    n = lsum.write_summary(args.out, rows)
    print(f"[summarize-layers] {args.out} ({n}レイヤー)")
    need = sum(1 for r in rows if str(r.get("needs_mapping")) == "true")
    warn = sum(1 for r in rows if r.get("warning"))
    print(f"  オブジェクト読込: {len(objs)} / 要マッピング: {need} / warning: {warn}")
    return 0


def cmd_init_layer_mapping(args: argparse.Namespace) -> int:
    summary = cu.read_dicts(args.summary)
    rows = lmap.init_mapping_from_summary(summary)
    n = lmap.write_mapping(args.out, rows)
    print(f"[init-layer-mapping] {args.out} ({n}レイヤーの雛形)")
    print("  ※ 自動推定値です。unit_price / calc_type / 寸法を確認・修正してください。")
    return 0


def cmd_update_layer_mapping(args: argparse.Namespace) -> int:
    summary = cu.read_dicts(args.summary)
    existing = lmap.read_mapping(args.mapping) if os.path.exists(args.mapping) else []
    merged, added = lmap.update_mapping(existing, summary)
    out = args.out or args.mapping
    n = lmap.write_mapping(out, merged)
    print(f"[update-layer-mapping] {out} (全{n}行 / 新規追加{len(added)})")
    if added:
        print("  追加レイヤー: " + ", ".join(added))
    else:
        print("  新規レイヤーなし（既存行は保持）")
    return 0


def cmd_estimate_by_layer(args: argparse.Namespace) -> int:
    summary = cu.read_dicts(args.summary)
    mapping = lmap.read_mapping(args.mapping)
    cost_rows = citems.read_cost_items(args.cost_items) if args.cost_items else None
    manual_prices = cu.read_dicts(args.manual_prices) if args.manual_prices else None
    conn = db.connect(args.db) if args.db else None

    results, summary_rows = lest.estimate_layers(
        summary, mapping, cost_rows=cost_rows, db_conn=conn,
        manual_prices=manual_prices, tax_rate=args.tax_rate)
    if conn:
        conn.close()

    lest.write_results(args.out, results)
    print(f"[estimate-by-layer] {args.out} ({len(results)}行)")
    if args.summary_out:
        lest.write_summary(args.summary_out, summary_rows)
        print(f"  総括: {args.summary_out}")
    if args.what_costs_out:
        lest.write_what_costs(args.what_costs_out, lest.build_what_costs(results, args.tax_rate))
        print(f"  何がいくらか: {args.what_costs_out}")

    levels = Counter(r["accuracy_level"] for r in results)
    review = sum(1 for r in results if str(r.get("needs_review")) == "true")
    print(f"  精度区分: {dict(levels)}")
    print(f"  needs_review: {review}")
    for sr in summary_rows:
        print(f"    {sr['category']:<18}: ¥{sr['subtotal_amount']:>12,} "
              f"({sr['item_count']}件, review {sr['needs_review_count']})")
    return 0


def cmd_init_samples(args: argparse.Namespace) -> int:
    written = samplegen.write_samples(args.out_dir)
    print(f"[init-samples] {len(written)}ファイルを {args.out_dir} に生成:")
    for w in written:
        print(f"  {w}")
    return 0


def cmd_mapping_ui(args: argparse.Namespace) -> int:
    from . import mapping_ui
    mapping_ui.run_server(args.out_dir, host=args.host, port=args.port,
                          tax_rate=args.tax_rate,
                          public_reference=getattr(args, "public_reference", "") or "")
    return 0


def cmd_compare_rhino_csv(args: argparse.Namespace) -> int:
    rep = rhino_csv.compare_rhino_csv(args.expected, args.actual)
    md = rhino_csv.render_compare_md(rep, args.expected, args.actual, _now_str())
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"[compare-rhino-csv] {args.out}")
    print(f"  期待{len(rep['expected_layers'])} / 実機{len(rep['actual_layers'])} / "
          f"未出力{len(rep['missing_in_actual'])} / 余分{len(rep['extra_in_actual'])}")
    print(f"  => {'一致（重大差分なし）' if rep['ok'] else '差分あり（レポート確認）'}")
    return 0 if rep["ok"] else 1


def cmd_estimate_public_rhino(args: argparse.Namespace) -> int:
    from . import public_rhino as pr
    try:
        res = pr.estimate_public_rhino(
            rhino_csv_path=args.rhino_csv, out_dir=args.out_dir, tax_rate=args.tax_rate,
            public_dir=args.public_dir or pr.DEFAULT_PUBLIC_DIR,
            plate_path=args.public_plate_reference or "",
            shape_path=args.public_shape_reference or "",
            now_str=_now_str())
    except FileNotFoundError as e:
        print(f"[estimate-public-rhino] 停止: {e}", file=sys.stderr)
        return 2
    s = res["stats"]
    print(f"[estimate-public-rhino] 完了 (out-dir: {args.out_dir})")
    print("  ※ 公開用参考価格（匿名化・集約・10円切上げ済）。実取引価格ではありません。")
    print(f"  レイヤー{s['layers']} / match {len(s['matched_layers'])} / "
          f"unmatched {len(s['unmatched_layers'])} / needs_review {s['needs_review']}")
    print(f"  税抜¥{s['subtotal_ex_tax']:,} + 税¥{s['tax_amount']:,} = 税込¥{s['subtotal_inc_tax']:,}")
    print(f"  recommended税込¥{s['recommended_inc_tax']:,} / conservative税込¥{s['conservative_inc_tax']:,}")
    print(f"  report: {res['report_path']}")
    if s["unmatched_layers"]:
        print("  unmatched: " + ", ".join(s["unmatched_layers"]))
    return 0


def cmd_release_audit(args: argparse.Namespace) -> int:
    from . import release_audit as ra
    rep = ra.run_release_audit(repo_root=args.repo_root or ".",
                               public_dir=args.public_dir or "./public_reference_data",
                               out=args.out or "./release_audit_report.md",
                               run_pytest=args.run_pytest, now_str=_now_str())
    print(f"[release-audit] {rep['report_path']}")
    for chk in rep["checks"]:
        mark = "OK " if chk["ok"] else "NG "
        print(f"  [{mark}] {chk['name']}: {chk['detail']}")
    print(f"  => {'公開可能（PASS）' if rep['ok'] else '要修正（FAIL）'}")
    return 0 if rep["ok"] else 1


def cmd_build_candidate_prices(args: argparse.Namespace) -> int:
    from . import candidate_prices as cp
    if not args.db and not args.input:
        print("[build-candidate-prices] --db または --input を指定してください", file=sys.stderr)
        return 2
    records = cp.load_records_from_db(args.db) if args.db else cp.load_records_from_csv(args.input)
    rows, warns = cp.build_candidates(records, vendor=args.vendor or "")
    cp.write_candidates(args.out, rows)
    summary = cp.aggregate(rows)
    summary_out = args.summary_out or args.out.replace(".csv", "_summary.csv")
    cp.write_summary(summary_out, summary)
    print(f"[build-candidate-prices] {args.out} ({len(rows)}件) / {summary_out} ({len(summary)}spec_key)")
    for w in warns:
        print(f"  [WARN] {w}")
    # class別件数
    by_class = {}
    for r in rows:
        by_class[r["candidate_class"]] = by_class.get(r["candidate_class"], 0) + 1
    print("  candidate_class:", by_class)
    if args.report_out:
        md = cp.build_report(rows, summary, args.vendor or "", _now_str())
        import os
        os.makedirs(os.path.dirname(os.path.abspath(args.report_out)), exist_ok=True)
        with open(args.report_out, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"  report: {args.report_out}")
    return 0


def cmd_suggest_prices_for_mapping(args: argparse.Namespace) -> int:
    from . import price_suggestions as ps
    mapping = lmap.read_mapping(args.mapping)
    summary = ps.read_summary(args.candidates)
    plate_ref = cu.read_dicts(args.plate_reference) if args.plate_reference else None
    rows = ps.suggest_for_mapping(mapping, summary, plate_reference_rows=plate_ref)
    ps.write_suggestions(args.out, rows)
    counts = ps.match_level_counts(rows)
    print(f"[suggest-prices-for-mapping] {args.out} ({len(rows)}件)")
    print(f"  match_level: {counts}")
    if args.failure_out:
        fail = ps.build_match_failure_analysis(mapping, summary)
        ps.write_match_failure_analysis(args.failure_out, fail)
        print(f"  failure-analysis: {args.failure_out} ({len(fail)}件)")
    print("  ※ 提案のみ。layer_mapping.csv へは自動反映しません（人間が確認して反映）。")
    return 0


def cmd_analyze_candidate_prices(args: argparse.Namespace) -> int:
    from . import price_analysis as pa
    rate = args.tax_rate
    cand = cu.read_dicts(args.candidates)
    summary = cu.read_dicts(args.summary)
    plate_ref = pa.build_plate_reference(cand, tax_rate=rate)
    plate_ref_summary = pa.build_plate_reference_summary(plate_ref, tax_rate=rate)
    master = pa.build_practical_master(summary, plate_ref_summary, tax_rate=rate)
    tables = pa.build_tables(cand, summary, master, plate_ref)

    written = pa.write_tables(args.tables_out, tables)
    pa.write_practical_master(args.practical_master_out, master)
    pa.write_plate_reference(args.plate_reference_out, plate_ref)
    pa.write_plate_reference_summary(args.plate_reference_summary_out, plate_ref_summary)
    # 価格レンジ（中央値〜最大値）は常に算出し、レポートに表を追記（item 9）
    from . import price_ranges as pr
    plate_rng = pr.build_plate_price_range_master(plate_ref, tax_rate=rate)
    shape_rng = pr.build_steel_shape_price_range_master(master, tax_rate=rate)
    report = pa.build_report(cand, summary, master, plate_ref, tables,
                             args.vendor or "", _now_str(), plate_ref_summary, tax_rate=rate)
    report += "\n\n---\n\n" + pr.build_range_report(plate_rng, shape_rng, rate, _now_str())
    pa.write_report(args.out, report)

    if getattr(args, "range_masters_out_dir", None):
        import os
        os.makedirs(args.range_masters_out_dir, exist_ok=True)
        pr.write_plate_price_range_master(
            os.path.join(args.range_masters_out_dir, "plate_price_range_master.csv"), plate_rng)
        pr.write_steel_shape_price_range_master(
            os.path.join(args.range_masters_out_dir, "steel_shape_price_range_master.csv"), shape_rng)
        print(f"  price_range_masters: {args.range_masters_out_dir} "
              f"(plate {len(plate_rng)} / shape {len(shape_rng)})")

    ready = sum(1 for m in master if m["usability"] == pa.U_READY)
    pref = sum(1 for m in master if m["candidate_class"] == "plate_reference")
    usable_ref = sum(1 for r in plate_ref if r["usable_as_reference"] == "true")
    print(f"[analyze-candidate-prices] report: {args.out}")
    print(f"  tables-out: {args.tables_out} ({len(written)}ファイル)")
    print(f"  practical_price_master: {args.practical_master_out} "
          f"({len(master)}件, ready={ready}, plate_reference={pref})")
    print(f"  plate_reference_price: {args.plate_reference_out} "
          f"({len(plate_ref)}件, usable_as_reference={usable_ref})")
    print(f"  plate_reference_summary_by_thickness: {args.plate_reference_summary_out} "
          f"({len(plate_ref_summary)}件)")
    return 0


def cmd_build_price_range_masters(args: argparse.Namespace) -> int:
    from . import price_ranges as pr
    rate = args.tax_rate
    plate_ref = cu.read_dicts(args.plate_reference)
    master = cu.read_dicts(args.practical_master)
    plate_rows = pr.build_plate_price_range_master(plate_ref, tax_rate=rate)
    shape_rows = pr.build_steel_shape_price_range_master(master, tax_rate=rate)

    import os
    os.makedirs(args.out_dir, exist_ok=True)
    plate_out = os.path.join(args.out_dir, "plate_price_range_master.csv")
    shape_out = os.path.join(args.out_dir, "steel_shape_price_range_master.csv")
    report_out = os.path.join(args.out_dir, "price_range_report.md")
    pr.write_plate_price_range_master(plate_out, plate_rows)
    pr.write_steel_shape_price_range_master(shape_out, shape_rows)
    pr.write_report(report_out, pr.build_range_report(plate_rows, shape_rows, rate, _now_str()))

    miss = pr.missing_thicknesses(plate_rows, "SS400")
    print(f"[build-price-range-masters] out-dir: {args.out_dir}")
    print(f"  plate_price_range_master: {plate_out} ({len(plate_rows)}件)")
    print(f"  steel_shape_price_range_master: {shape_out} ({len(shape_rows)}件)")
    print(f"  price_range_report: {report_out}")
    print(f"  SS400で欠けている板厚: {', '.join('t'+str(t) for t in miss) or 'なし'}")
    return 0


def cmd_build_public_reference_prices(args: argparse.Namespace) -> int:
    from . import public_data as pub
    import os
    plate_range = cu.read_dicts(args.plate_range_master)
    shape_range = cu.read_dicts(args.shape_range_master)
    plate_pub = pub.build_public_plate(plate_range, tax_rate=args.tax_rate, unit=args.rounding)
    shape_pub = pub.build_public_shape(shape_range, tax_rate=args.tax_rate, unit=args.rounding)
    os.makedirs(args.out_dir, exist_ok=True)
    p_out = os.path.join(args.out_dir, "public_plate_reference_prices.csv")
    s_out = os.path.join(args.out_dir, "public_shape_reference_prices.csv")
    n_out = os.path.join(args.out_dir, "public_reference_price_notes.md")
    pub.write_public_plate(p_out, plate_pub)
    pub.write_public_shape(s_out, shape_pub)
    pub.write_notes(n_out, pub.build_notes_md(plate_pub, shape_pub, args.tax_rate, args.rounding))
    print(f"[build-public-reference-prices] out-dir: {args.out_dir} (丸め{args.rounding}円・切り上げ)")
    print(f"  public_plate_reference_prices: {p_out} ({len(plate_pub)}件)")
    print(f"  public_shape_reference_prices: {s_out} ({len(shape_pub)}件)")
    print(f"  public_reference_price_notes: {n_out}")
    print("  ※ 取引先名/見積日/PDF名/個別明細は削除済み。10円単位切り上げの参考値。")
    return 0


def cmd_audit_public_data(args: argparse.Namespace) -> int:
    from . import public_data as pub
    rep = pub.audit_public_dir(args.public_dir, repo_root=args.repo_root or ".")
    print(f"[audit-public-data] {args.public_dir}")
    print(f"  検査ファイル: {', '.join(rep['checked']) or '(なし)'}")
    if rep["ok"]:
        print("  => OK: 公開可能（禁止列・取引先名・PDF名・見積日・実明細なし）")
        return 0
    print("  => NG: 以下を修正してください")
    for x in rep["issues"]:
        print(f"   - {x}")
    return 1


def cmd_run_demo(args: argparse.Namespace) -> int:
    from . import public_data as pub
    from . import enrich
    from . import layer_estimate as lest
    import os

    pdir = args.public_dir or "./public_reference_data"
    plate_csv = os.path.join(pdir, "public_plate_reference_prices.csv")
    shape_csv = os.path.join(pdir, "public_shape_reference_prices.csv")
    if not (os.path.exists(plate_csv) and os.path.exists(shape_csv)):
        alt = "./samples/reference_prices"
        if os.path.exists(os.path.join(alt, "public_plate_reference_prices.csv")):
            pdir = alt
            plate_csv = os.path.join(pdir, "public_plate_reference_prices.csv")
            shape_csv = os.path.join(pdir, "public_shape_reference_prices.csv")
        else:
            print(f"[run-demo] 公開参考単価が見つかりません: {pdir}", file=sys.stderr)
            print("  先に build-public-reference-prices を実行してください。", file=sys.stderr)
            return 2

    plate_pub = cu.read_dicts(plate_csv)
    shape_pub = cu.read_dicts(shape_csv)
    plate_range = pub.public_plate_to_range(plate_pub)
    shape_range = pub.public_shape_to_range(shape_pub)

    summary, mapping = pub.build_demo_inputs()
    enriched = enrich.enrich_mapping(mapping, [], [], tax_rate=args.tax_rate,
                                     plate_range_rows=plate_range, shape_range_rows=shape_range)
    results, summ = lest.estimate_layers(summary, enriched, tax_rate=args.tax_rate)

    os.makedirs(args.out_dir, exist_ok=True)
    lest.write_results(os.path.join(args.out_dir, "estimate_result.csv"), results)
    lest.write_summary(os.path.join(args.out_dir, "estimate_summary.csv"), summ)
    what = lest.build_what_costs(results, args.tax_rate)
    lest.write_what_costs(os.path.join(args.out_dir, "what_costs_how_much.csv"), what)

    print(f"[run-demo] 公開参考単価で完走 (in: {pdir} / out: {args.out_dir})")
    print("  参考価格（税抜→税込 / recommended=中央値相当, conservative=最大値相当, 手入力変更可）:")
    for w in what:
        if w.get("recommended_amount_ex_tax"):
            print(f"   - {w['item_name']:<18} 単価税抜¥{w['unit_price_ex_tax']}/{w['price_unit']} "
                  f"→税込¥{w['unit_price_inc_tax']} | 中央¥{w['recommended_amount_ex_tax']} "
                  f"/ 最大¥{w['conservative_amount_ex_tax']}（税込¥{w['conservative_amount_inc_tax']}）")
    total = next((s for s in summ if str(s["category"]).startswith("TOTAL")), {})
    print(f"  合計: 中央税抜¥{total.get('recommended_subtotal_ex_tax','')} / "
          f"最大税込¥{total.get('conservative_subtotal_inc_tax','')}")
    return 0


def cmd_enrich_layer_mapping(args: argparse.Namespace) -> int:
    from . import enrich
    mapping = lmap.read_mapping(args.mapping)
    summary = cu.read_dicts(args.summary)
    master = cu.read_dicts(args.practical_master)
    # --plate-reference（板厚別サマリ）を渡された場合は master に統合して板材候補を増やす
    if getattr(args, "plate_reference", None):
        for pr in cu.read_dicts(args.plate_reference):
            master.append({
                "candidate_class": "plate_reference",
                "material_category": "plate",
                "material_grade": pr.get("material_grade", ""),
                "spec_key": f"plate_ref|{pr.get('material_grade','')}|"
                            f"t{pr.get('thickness_mm','')}|{pr.get('plate_class','')}",
                "price_per_kg": pr.get("median_price_per_kg", ""),
                "latest_quote_date": pr.get("latest_quote_date", ""),
                "confidence": pr.get("confidence", 0.4),
                "usable_as_base_price": "false",
                "usable_as_reference": "true",
            })
    plate_range = cu.read_dicts(args.plate_range_master) if getattr(args, "plate_range_master", None) else None
    shape_range = cu.read_dicts(args.shape_range_master) if getattr(args, "shape_range_master", None) else None
    # 公開用参考単価をfallbackとして利用（実データのrange masterが無い場合）
    if getattr(args, "public_plate_reference", None):
        from . import public_data as pub
        plate_range = (plate_range or []) + pub.public_plate_to_range(cu.read_dicts(args.public_plate_reference))
    if getattr(args, "public_shape_reference", None):
        from . import public_data as pub
        shape_range = (shape_range or []) + pub.public_shape_to_range(cu.read_dicts(args.public_shape_reference))
    enriched = enrich.enrich_mapping(mapping, summary, master, tax_rate=args.tax_rate,
                                     plate_range_rows=plate_range, shape_range_rows=shape_range)
    enrich.write_enriched(args.out, enriched)
    n_cells = enrich.enriched_field_count(mapping, enriched)
    print(f"[enrich-layer-mapping] {args.out} ({len(enriched)}行)")
    print(f"  補完セル数: {n_cells}")
    print(f"  ※ 元mapping({args.mapping})は上書きしません。unit_priceは税抜。"
          f"補完欄は notes に '{enrich.ENRICH_NOTE}'＋税込参考を付与（人間が承認）。")
    return 0


def cmd_audit_rhino_geometry(args: argparse.Namespace) -> int:
    from . import rhino_audit
    rep = rhino_audit.audit_rhino_geometry(args.input)
    now = _now_str()
    rhino_audit.write_audit_md(rep, args.input, args.out, now)
    st = rep["stats"]
    print(f"[audit-rhino-geometry] {args.out}")
    print(f"  行数: {st['rows']} / レイヤー数: {st['layers']}")
    print(f"  error: {st['errors']} / warning: {st['warnings']} / info: {st['infos']}")
    for f in rep["findings"]:
        print(f"  [{f['severity'].upper():<7}] {f['title']}: {f['count']}件")
    return 0


def cmd_run_rhino_estimate(args: argparse.Namespace) -> int:
    from . import rhino_run
    try:
        res = rhino_run.run_rhino_estimate(
            rhino_csv_path=args.rhino_csv, mapping_path=args.mapping,
            cost_items_path=args.cost_items, out_dir=args.out_dir,
            db_path=args.db, manual_prices_path=args.manual_prices,
            now_str=_now_str(), tax_rate=args.tax_rate)
    except rhino_run.RhinoEstimateError as e:
        print(f"[run-rhino-estimate] 停止: {e}", file=sys.stderr)
        return 2
    s = res["stats"]
    print(f"[run-rhino-estimate] 完了 (out-dir: {args.out_dir})")
    print(f"  layer_summary       : {res['summary_path']}")
    print(f"  mapping({res['mapping_mode']}) : {res['mapping_out']}")
    print(f"  estimate_result     : {res['result_path']}")
    print(f"  estimate_summary    : {res['summary_out']}")
    print(f"  what_costs_how_much : {res['what_costs_path']}")
    print(f"  report              : {res['report_path']}")
    print(f"  レイヤー {s['layers']} / 見積確定 {s['mapped_ok']} / "
          f"未設定 {s['unmapped']} / needs_review {s['needs_review']} / warning {s['warnings']}")
    print(f"  概算合計: 税抜¥{int(s['estimated_total_ex_tax']):,} "
          f"+ 税¥{int(s['estimated_tax']):,} = 税込¥{int(s['estimated_total_inc_tax']):,}")
    if s["unmapped_names"]:
        print("  未設定レイヤー: " + ", ".join(s["unmapped_names"]))
    return 0


def cmd_validate_rhino_csv(args: argparse.Namespace) -> int:
    rep = rhino_csv.validate_rhino_csv(args.input)
    st = rep["stats"]
    print(f"[validate-rhino-csv] {args.input}")
    print(f"  行数: {st['rows']} / レイヤー数: {st['layers']}")
    print(f"  面積取得: {st['with_area']} / 体積取得: {st['with_volume']} "
          f"/ 曲線長取得: {st['with_curve_length']}")
    print(f"  形状量ゼロ行: {st['zero_geometry']} / notesあり: {st['with_notes']}")
    for e in rep["errors"]:
        print(f"  [ERROR] {e}")
    for w in rep["warnings"]:
        print(f"  [WARN ] {w}")
    if rep["ok"]:
        print("  => OK: summarize-layers でそのまま処理できます。")
        return 0
    print("  => NG: 上記エラーを修正してください。")
    return 1


def cmd_suggest_layer(args: argparse.Namespace) -> int:
    sug = lsum.suggest_for_layer(args.layer_name)
    print(f"[suggest-layer] '{args.layer_name}' の自動推定（※確定値ではありません）:")
    for k, v in sug.items():
        print(f"  {k:<28}: {v if v is not None else ''}")
    print("  → 最終的な計算は layer_mapping.csv の編集値を正とします。")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="steel_estimator", description="鋼材見積PDF解析・概算見積ツール")
    sub = p.add_subparsers(dest="command", required=True)

    pi = sub.add_parser("ingest", help="PDF群を解析しCSV/SQLiteへ保存")
    pi.add_argument("--pdf-dir", required=True)
    pi.add_argument("--out", help="抽出結果CSVの出力先")
    pi.add_argument("--db", help="SQLite保存先")
    pi.add_argument("--limit", type=int, default=0, help="先頭N件のみ処理（dry-run用）")
    pi.set_defaults(func=cmd_ingest)

    pr = sub.add_parser("export-review", help="レビュー用CSVを出力")
    pr.add_argument("--db", required=True)
    pr.add_argument("--out", required=True)
    pr.set_defaults(func=cmd_export_review)

    pe = sub.add_parser("estimate", help="material_request.csvから概算見積")
    pe.add_argument("--input", required=True)
    pe.add_argument("--db", required=True)
    pe.add_argument("--out", required=True)
    pe.add_argument("--tax-rate", type=float, default=DEFAULT_TAX_RATE,
                    help="消費税率（既定0.10）。estimated_amountは税抜")
    pe.set_defaults(func=cmd_estimate)

    # --- Rhinoレイヤー見積系 ---
    ps = sub.add_parser("summarize-layers", help="rhino_objects.csv→layer_summary.csv")
    ps.add_argument("--input", required=True)
    ps.add_argument("--out", required=True)
    ps.set_defaults(func=cmd_summarize_layers)

    pim = sub.add_parser("init-layer-mapping", help="layer_summaryからmapping雛形を生成")
    pim.add_argument("--summary", required=True)
    pim.add_argument("--out", required=True)
    pim.set_defaults(func=cmd_init_layer_mapping)

    pum = sub.add_parser("update-layer-mapping", help="既存mappingを壊さず新規レイヤー追記")
    pum.add_argument("--summary", required=True)
    pum.add_argument("--mapping", required=True)
    pum.add_argument("--out", help="未指定なら --mapping を上書き")
    pum.set_defaults(func=cmd_update_layer_mapping)

    pel = sub.add_parser("estimate-by-layer", help="layer_mappingを正として概算見積")
    pel.add_argument("--summary", required=True)
    pel.add_argument("--mapping", required=True)
    pel.add_argument("--cost-items", help="加工費等のcost_items.csv")
    pel.add_argument("--db", help="PDF単価DB（候補・補助。任意）")
    pel.add_argument("--manual-prices", help="manual_prices.csv（任意）")
    pel.add_argument("--out", required=True)
    pel.add_argument("--summary-out", help="estimate_summary.csvの出力先")
    pel.add_argument("--what-costs-out", help="what_costs_how_much.csvの出力先（任意）")
    pel.add_argument("--tax-rate", type=float, default=DEFAULT_TAX_RATE,
                     help="消費税率（既定0.10）")
    pel.set_defaults(func=cmd_estimate_by_layer)

    pis = sub.add_parser("init-samples", help="サンプルCSV/ガイドを生成")
    pis.add_argument("--out-dir", required=True)
    pis.set_defaults(func=cmd_init_samples)

    psl = sub.add_parser("suggest-layer", help="レイヤー名の自動推定だけ確認")
    psl.add_argument("--layer-name", required=True)
    psl.set_defaults(func=cmd_suggest_layer)

    pv = sub.add_parser("validate-rhino-csv", help="rhino_objects.csvの妥当性検証")
    pv.add_argument("--input", required=True)
    pv.set_defaults(func=cmd_validate_rhino_csv)

    pa = sub.add_parser("audit-rhino-geometry", help="rhino_objects.csvの作図品質監査")
    pa.add_argument("--input", required=True)
    pa.add_argument("--out", required=True)
    pa.set_defaults(func=cmd_audit_rhino_geometry)

    pbc = sub.add_parser("build-candidate-prices", help="PDF単価DBから候補単価マスターを生成")
    pbc.add_argument("--db", help="steel_quotes.sqlite")
    pbc.add_argument("--input", help="extracted_materials.csv（--dbの代わり）")
    pbc.add_argument("--vendor", default="", help="業者名フィルタ（部分一致）")
    pbc.add_argument("--out", required=True)
    pbc.add_argument("--summary-out", help="集約CSVの出力先")
    pbc.add_argument("--report-out", help="レポートMarkdownの出力先")
    pbc.set_defaults(func=cmd_build_candidate_prices)

    psp = sub.add_parser("suggest-prices-for-mapping", help="mappingへ候補単価を提案（自動反映しない）")
    psp.add_argument("--mapping", required=True)
    psp.add_argument("--candidates", required=True, help="toko_candidate_price_summary.csv")
    psp.add_argument("--out", required=True)
    psp.add_argument("--failure-out", help="match_failure_analysis.csvの出力先（任意）")
    psp.add_argument("--plate-reference",
                     help="plate_reference_summary_by_thickness.csv（板材フォールバック用・任意）")
    psp.set_defaults(func=cmd_suggest_prices_for_mapping)

    pac = sub.add_parser("analyze-candidate-prices",
                         help="候補単価DBを分析（レポート・実用単価マスター・板材参考・分析テーブル）")
    pac.add_argument("--candidates", required=True, help="toko_candidate_prices.csv（明細）")
    pac.add_argument("--summary", required=True, help="toko_candidate_price_summary.csv（集約）")
    pac.add_argument("--out", required=True, help="分析レポート Markdown の出力先")
    pac.add_argument("--tables-out", required=True, help="分析テーブルCSV群の出力ディレクトリ")
    pac.add_argument("--practical-master-out", default="./data/toko_practical_price_master.csv")
    pac.add_argument("--plate-reference-out", default="./data/plate_reference_price.csv")
    pac.add_argument("--plate-reference-summary-out",
                     default="./data/plate_reference_summary_by_thickness.csv")
    pac.add_argument("--vendor", default="", help="業者名（レポート表示用）")
    pac.add_argument("--range-masters-out-dir",
                     help="価格レンジマスター(plate/shape)も出力するディレクトリ（任意）")
    pac.add_argument("--tax-rate", type=float, default=DEFAULT_TAX_RATE,
                     help="消費税率（既定0.10）。既存単価列は税抜、*_inc_taxが税込")
    pac.set_defaults(func=cmd_analyze_candidate_prices)

    pen = sub.add_parser("enrich-layer-mapping",
                         help="layer_mappingの空欄を補完候補で埋める（元は上書きしない）")
    pen.add_argument("--mapping", required=True)
    pen.add_argument("--summary", required=True, help="layer_summary.csv")
    pen.add_argument("--practical-master", required=True,
                     help="toko_practical_price_master.csv")
    pen.add_argument("--plate-reference",
                     help="plate_reference_summary_by_thickness.csv（板材候補補強・任意）")
    pen.add_argument("--plate-range-master",
                     help="plate_price_range_master.csv（中央値/最大値レンジ・任意）")
    pen.add_argument("--shape-range-master",
                     help="steel_shape_price_range_master.csv（中央値/最大値レンジ・任意）")
    pen.add_argument("--public-plate-reference",
                     help="public_plate_reference_prices.csv（公開参考・fallback・任意）")
    pen.add_argument("--public-shape-reference",
                     help="public_shape_reference_prices.csv（公開参考・fallback・任意）")
    pen.add_argument("--out", required=True, help="layer_mapping_enriched.csv")
    pen.add_argument("--tax-rate", type=float, default=DEFAULT_TAX_RATE,
                     help="消費税率（既定0.10）。unit_priceは税抜、税込はnotesに参考表示")
    pen.set_defaults(func=cmd_enrich_layer_mapping)

    pprm = sub.add_parser("build-price-range-masters",
                          help="板厚別・鋼材種別の価格レンジマスター（中央値〜最大値）を生成")
    pprm.add_argument("--plate-reference", required=True,
                      help="plate_reference_price.csv（明細）")
    pprm.add_argument("--practical-master", required=True,
                      help="toko_practical_price_master.csv")
    pprm.add_argument("--out-dir", required=True)
    pprm.add_argument("--tax-rate", type=float, default=DEFAULT_TAX_RATE,
                      help="消費税率（既定0.10）")
    pprm.set_defaults(func=cmd_build_price_range_masters)

    ppub = sub.add_parser("build-public-reference-prices",
                          help="公開用の匿名化・集約・10円切り上げ済み参考単価CSVを生成")
    ppub.add_argument("--plate-range-master", required=True)
    ppub.add_argument("--shape-range-master", required=True)
    ppub.add_argument("--out-dir", required=True)
    ppub.add_argument("--rounding", type=int, default=10, help="丸め単位（円・切り上げ。既定10）")
    ppub.add_argument("--tax-rate", type=float, default=DEFAULT_TAX_RATE)
    ppub.set_defaults(func=cmd_build_public_reference_prices)

    paud = sub.add_parser("audit-public-data",
                          help="公開ディレクトリに実データ(取引先名/PDF/見積日/明細)が無いか監査")
    paud.add_argument("--public-dir", required=True)
    paud.add_argument("--repo-root", default=".", help="gitignore/追跡確認のルート（既定.）")
    paud.set_defaults(func=cmd_audit_public_data)

    pdemo = sub.add_parser("run-demo", help="公開参考単価だけで概算見積デモを実行（実データ不要）")
    pdemo.add_argument("--out-dir", required=True)
    pdemo.add_argument("--public-dir", help="公開参考単価フォルダ（既定 ./public_reference_data）")
    pdemo.add_argument("--tax-rate", type=float, default=DEFAULT_TAX_RATE)
    pdemo.set_defaults(func=cmd_run_demo)

    pui = sub.add_parser("mapping-ui", help="候補単価選択UI（ローカルWeb）を起動")
    pui.add_argument("--out-dir", required=True)
    pui.add_argument("--host", default="127.0.0.1")
    pui.add_argument("--port", type=int, default=8765)
    pui.add_argument("--tax-rate", type=float, default=DEFAULT_TAX_RATE,
                     help="消費税率（既定0.10）。単価は税抜保存、税込は表示のみ")
    pui.add_argument("--public-reference",
                     help="公開参考価格フォルダ（out-dirに未配置ならコピーして参照）")
    pui.set_defaults(func=cmd_mapping_ui)

    pepr = sub.add_parser("estimate-public-rhino",
                          help="rhino_objects.csvを公開参考単価だけで一括見積（実データ不要）")
    pepr.add_argument("--rhino-csv", required=True)
    pepr.add_argument("--out-dir", required=True)
    pepr.add_argument("--tax-rate", type=float, default=DEFAULT_TAX_RATE)
    pepr.add_argument("--public-dir", help="公開参考単価フォルダ（既定 ./public_reference_data）")
    pepr.add_argument("--public-plate-reference", help="板材参考CSV（個別指定）")
    pepr.add_argument("--public-shape-reference", help="形鋼参考CSV（個別指定）")
    pepr.set_defaults(func=cmd_estimate_public_rhino)

    pcmp = sub.add_parser("compare-rhino-csv", help="期待CSVと実機CSVの差分レポート")
    pcmp.add_argument("--expected", default="./samples/rhino_objects_demo.csv")
    pcmp.add_argument("--actual", required=True)
    pcmp.add_argument("--out", default="./data/rhino_csv_compare_report.md")
    pcmp.set_defaults(func=cmd_compare_rhino_csv)

    prel = sub.add_parser("release-audit", help="公開前監査（実データ混入/デモ/Rhino/README確認）")
    prel.add_argument("--repo-root", default=".")
    prel.add_argument("--public-dir", default="./public_reference_data")
    prel.add_argument("--out", default="./release_audit_report.md")
    prel.add_argument("--run-pytest", action="store_true", help="pytestもサブプロセスで実行")
    prel.set_defaults(func=cmd_release_audit)

    prr = sub.add_parser("run-rhino-estimate", help="CSVから見積一式を一括実行")
    prr.add_argument("--rhino-csv", required=True)
    prr.add_argument("--mapping", help="既存mapping（あれば保持し新規だけ追加）")
    prr.add_argument("--cost-items", help="加工費等のcost_items.csv")
    prr.add_argument("--db", help="PDF単価DB（候補・補助。任意）")
    prr.add_argument("--manual-prices", help="manual_prices.csv（任意）")
    prr.add_argument("--out-dir", required=True)
    prr.add_argument("--tax-rate", type=float, default=DEFAULT_TAX_RATE,
                     help="消費税率（既定0.10）")
    prr.set_defaults(func=cmd_run_rhino_estimate)
    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
