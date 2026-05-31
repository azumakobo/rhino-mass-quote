"""公開前監査（release-audit）。

実データ混入の有無・公開価格CSV・デモ完走・Rhino公開見積完走・README/docs/gitignore を
まとめて検査し、release_audit_report.md を出力する。実データ・実単価は一切使わない。
"""

from __future__ import annotations

import os
import tempfile

from . import csv_utils as cu


def _check(name, ok, detail):
    return {"name": name, "ok": bool(ok), "detail": detail}


def run_release_audit(repo_root: str = ".", public_dir: str = "./public_reference_data",
                      out: str = "./release_audit_report.md", run_pytest: bool = False,
                      now_str: str = "") -> dict:
    from . import public_data as pub
    checks = []

    # 1. 実データ混入監査（取引先名/PDF名/見積日/明細/禁止列）
    try:
        adp = pub.audit_public_dir(public_dir, repo_root=repo_root)
        checks.append(_check("実データ非混入(audit-public-data)", adp["ok"],
                             "OK" if adp["ok"] else "; ".join(adp.get("findings", []))[:300]))
    except Exception as e:
        checks.append(_check("実データ非混入(audit-public-data)", False, f"例外: {e}"))

    # 2. 公開価格CSVの存在
    plate = os.path.join(public_dir, "public_plate_reference_prices.csv")
    shape = os.path.join(public_dir, "public_shape_reference_prices.csv")
    have_prices = os.path.exists(plate) and os.path.exists(shape)
    checks.append(_check("公開参考価格CSV存在", have_prices,
                         f"{plate} / {shape}" if have_prices else "見つかりません"))

    # 3. 価格CSVに禁止列が無い
    checks.append(_check("価格CSVに禁止列なし", *_forbidden_columns(plate, shape)))

    # 4. run-demo 完走（公開価格のみ）
    checks.append(_check("run-demo 完走", *_try_run_demo(public_dir)))

    # 5. Rhinoサンプルで estimate-public-rhino 完走
    checks.append(_check("estimate-public-rhino 完走（サンプル）",
                         *_try_public_rhino(repo_root, public_dir)))

    # 6. README 存在
    readme = _first_existing(repo_root, ["README.md", "readme.md"])
    checks.append(_check("README存在", bool(readme), readme or "なし"))

    # 7. docs/data-security.md 存在
    dsec = os.path.join(repo_root, "docs", "data-security.md")
    checks.append(_check("docs/data-security.md存在", os.path.exists(dsec), dsec))

    # 8. public_reference_data 存在
    checks.append(_check("public_reference_data存在", os.path.isdir(public_dir), public_dir))

    # 9. .gitignore に必須パターン
    checks.append(_check(".gitignore保護", *_gitignore_ok(repo_root)))

    # 10. 禁止ファイルがリポジトリ直下に追跡されていない
    checks.append(_check("禁止ファイル非追跡(.pdf/.sqlite/.3dm等)", *_forbidden_files(repo_root)))

    # 11. pytest（任意）
    if run_pytest:
        checks.append(_check("pytest", *_run_pytest(repo_root)))
    else:
        checks.append(_check("pytest", True, "スキップ（--run-pytest で実行可）"))

    ok = all(c["ok"] for c in checks)
    report_path = os.path.abspath(out)
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(_render(checks, ok, public_dir, now_str))
    return {"ok": ok, "checks": checks, "report_path": report_path}


# ---- 個別チェック ----

def _forbidden_columns(plate, shape):
    forbidden = ("vendor", "取引先", "業者", "quote_date", "見積日", "source_pdf", "pdf",
                 "顧客", "customer", "amount", "明細", "unit_price_raw")
    bad = []
    for p in (plate, shape):
        if not os.path.exists(p):
            continue
        rows = cu.read_dicts(p)
        if not rows:
            continue
        for col in rows[0].keys():
            cl = col.lower()
            for fb in forbidden:
                if fb in cl:
                    bad.append(f"{os.path.basename(p)}:{col}")
    return (not bad, "OK" if not bad else "禁止列: " + ", ".join(bad))


def _try_run_demo(public_dir):
    from . import public_data as pub
    from . import enrich
    from . import layer_estimate as lest
    try:
        plate = pub.public_plate_to_range(cu.read_dicts(
            os.path.join(public_dir, "public_plate_reference_prices.csv")))
        shape = pub.public_shape_to_range(cu.read_dicts(
            os.path.join(public_dir, "public_shape_reference_prices.csv")))
        summary, mapping = pub.build_demo_inputs()
        enriched = enrich.enrich_mapping(mapping, [], [], plate_range_rows=plate,
                                         shape_range_rows=shape)
        results, summ = lest.estimate_layers(summary, enriched)
        total = next((s for s in summ if str(s["category"]).startswith("TOTAL")), {})
        return (bool(results), f"税込合計¥{total.get('subtotal_amount_inc_tax', 0):,}")
    except Exception as e:
        return (False, f"例外: {e}")


def _try_public_rhino(repo_root, public_dir):
    from . import public_rhino as pr
    sample = os.path.join(repo_root, "samples", "rhino_objects_demo.csv")
    if not os.path.exists(sample):
        return (False, f"サンプルなし: {sample}")
    try:
        with tempfile.TemporaryDirectory() as td:
            res = pr.estimate_public_rhino(sample, td, public_dir=public_dir)
            s = res["stats"]
            ok = os.path.exists(os.path.join(td, "what_costs_how_much.csv")) \
                and len(s["matched_layers"]) > 0
            return (ok, f"match {len(s['matched_layers'])} / 税込¥{s['subtotal_inc_tax']:,}")
    except Exception as e:
        return (False, f"例外: {e}")


def _first_existing(root, names):
    for n in names:
        p = os.path.join(root, n)
        if os.path.exists(p):
            return p
    return ""


def _gitignore_ok(root):
    p = os.path.join(root, ".gitignore")
    if not os.path.exists(p):
        return (False, ".gitignore なし")
    txt = open(p, encoding="utf-8", errors="ignore").read()
    need = ["*.pdf", "*.sqlite", "data/", "*.3dm"]
    missing = [n for n in need if n not in txt]
    return (not missing, "OK" if not missing else "未保護: " + ", ".join(missing))


def _forbidden_files(root):
    """公開（コミット）対象に実データ拡張子が含まれないか。

    git管理下なら追跡ファイルのみを対象（gitignore済みのローカル実データは公開されないので除外）。
    git不在時は gitignore 済みの実データ置き場を除外して走査する。
    """
    exts = (".pdf", ".sqlite", ".db", ".3dm")
    import subprocess
    try:
        r = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True,
                           text=True, timeout=30)
        if r.returncode == 0:
            tracked = [ln for ln in r.stdout.splitlines() if ln.lower().endswith(exts)]
            return (not tracked, "OK(git追跡なし)" if not tracked else "追跡中: " + ", ".join(tracked[:10]))
    except Exception:
        pass
    # フォールバック: gitignore済みの実データ置き場を除外して走査
    skip = {".git", ".venv", "__pycache__", "node_modules", "data", "quotes",
            "akiyama_quotes", "demo_output", "public_demo_output"}
    bad = []
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in skip]
        for fn in files:
            if fn.lower().endswith(exts):
                bad.append(os.path.relpath(os.path.join(dirpath, fn), root))
    return (not bad, "OK(gitignore済み実データ除く)" if not bad else "検出: " + ", ".join(bad[:10]))


def _run_pytest(root):
    import subprocess
    try:
        r = subprocess.run(["python", "-m", "pytest", "-q"], cwd=root,
                           capture_output=True, text=True, timeout=600)
        tail = (r.stdout or r.stderr).strip().splitlines()[-1] if (r.stdout or r.stderr) else ""
        return (r.returncode == 0, tail[:120])
    except Exception as e:
        return (False, f"例外: {e}")


def _render(checks, ok, public_dir, now_str) -> str:
    L = ["# 公開前監査レポート (release-audit)", ""]
    if now_str:
        L.append(f"- 実行: {now_str}")
    L += [f"- public_dir: `{public_dir}`",
          f"- 総合判定: {'✅ 公開可能 (PASS)' if ok else '❌ 要修正 (FAIL)'}",
          "", "## チェック結果", "| 項目 | 判定 | 詳細 |", "|---|:--:|---|"]
    for c in checks:
        L.append(f"| {c['name']} | {'OK' if c['ok'] else 'NG'} | {c['detail']} |")
    L += ["", "> 実データ・実単価は使用していません。公開用参考価格は匿名化・集約・10円切上げ済です。"]
    return "\n".join(L) + "\n"
