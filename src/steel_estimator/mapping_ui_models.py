"""候補単価選択UI のデータ層（FastAPI非依存・テスト可能）。

役割:
  - out-dir 内の各CSVを読み、ダッシュボード/レイヤー詳細用のデータを組み立てる。
  - 候補単価のフォーム反映（保存はしない）。
  - 承認時の保存（layer_mapping_approved.csv）・バックアップ・承認ログ。

原則:
  - 既存 layer_mapping.csv / layer_mapping_updated.csv は上書きしない。保存先は approved。
  - 候補は人間が選ぶための提示。生材単価と加工品単価を混ぜない（加工品候補は強く警告）。
"""

from __future__ import annotations

import os
import shutil

from . import csv_utils as cu
from . import layer_mapping as lmap
from . import layer_estimate as lest
from . import settings as tx


APPROVED_NAME = "layer_mapping_approved.csv"
LOG_NAME = "mapping_approval_log.csv"

APPROVAL_LOG_FIELDS = (
    "timestamp", "layer_name", "old_unit_price", "new_unit_price",
    "old_price_unit", "new_price_unit", "selected_spec_key", "selected_vendor",
    "selected_quote_date", "match_level", "confidence", "note",
)

# 単価必須の calc_type（未入力なら要対応）
_PRICE_REQUIRED = lest._PRICE_REQUIRED


def resolve_mapping_path(out_dir: str) -> str:
    """現在の編集ベースにする mapping を決める。

    approved があればそれを継続編集、なければ updated、なければ base。
    """
    # approved > updated > enriched(公開デモ) > initial(公開デモ) > base
    for name in (APPROVED_NAME, "layer_mapping_updated.csv",
                 "layer_mapping_enriched.csv", "layer_mapping_initial.csv",
                 "layer_mapping.csv"):
        p = os.path.join(out_dir, name)
        if os.path.exists(p):
            return p
    return os.path.join(out_dir, "layer_mapping.csv")


def load_state(out_dir: str) -> dict:
    """UI が使う全データを読み込む。"""
    mapping_path = resolve_mapping_path(out_dir)
    mapping_rows = lmap.read_mapping(mapping_path) if os.path.exists(mapping_path) else []

    def _read(name):
        p = os.path.join(out_dir, name)
        return cu.read_dicts(p) if os.path.exists(p) else []

    summary_rows = _read("layer_summary.csv")
    suggestions = _read("layer_mapping_price_suggestions.csv")
    candidates = _read("toko_candidate_price_summary.csv")
    estimate_summary = _read("estimate_summary.csv")

    return {
        "out_dir": out_dir,
        "mapping_path": mapping_path,
        "mapping_rows": mapping_rows,
        "summary_by_layer": {r.get("layer_name", ""): r for r in summary_rows},
        "suggestions_by_layer": {r.get("layer_name", ""): r for r in suggestions},
        "candidates": candidates,
        "estimate_summary": estimate_summary,
    }


# ============================================================
# ダッシュボード
# ============================================================

def _needs_price(row: dict) -> bool:
    calc = (row.get("calc_type", "") or "").strip()
    if calc in _PRICE_REQUIRED:
        return not (row.get("unit_price", "") or "").strip()
    if calc == lmap.CALC_FIXED_AMOUNT:
        return not (row.get("fixed_amount", "") or "").strip()
    if calc == "":
        return True
    return False  # ignore 等


def price_tax_view(ex, tax_rate=tx.DEFAULT_TAX_RATE) -> dict:
    """単価/金額の税抜・税額・税込・税率を表示用に返す（UIテンプレート用）。"""
    return tx.tax_view(ex, tax_rate)


def dashboard_data(state: dict, tax_rate=tx.DEFAULT_TAX_RATE) -> dict:
    rate = tx.normalize_rate(tax_rate)
    rows = state["mapping_rows"]
    needs = [r for r in rows if _needs_price(r)]
    sugg = list(state["suggestions_by_layer"].values())
    levels = {"exact": 0, "close": 0, "category_only": 0, "none": 0}
    for s in sugg:
        lv = s.get("match_level", "none")
        levels[lv] = levels.get(lv, 0) + 1

    total = ""
    total_ex = total_tax = total_inc = ""
    for r in state["estimate_summary"]:
        if str(r.get("category", "")).startswith("TOTAL"):
            total = r.get("subtotal_amount", "")
            # estimate_summary が税列を持てばそれを使い、無ければ税率から算出
            total_ex = r.get("subtotal_amount_ex_tax", "") or total
            total_tax = r.get("tax_amount", "") or tx._fmt(tx.tax_of(total_ex, rate))
            total_inc = r.get("subtotal_amount_inc_tax", "") or tx._fmt(tx.inc_of(total_ex, rate))
            break

    return {
        "layers": len(rows),
        "mapped": len(rows) - len(needs),
        "unmapped": len(needs),
        "needs_review": sum(1 for r in rows if cu.to_bool(_review_flag(r, state), default=False)),
        "warning": sum(1 for r in (state["summary_by_layer"].values()) if (r.get("warning") or "").strip()),
        "suggestion_count": len(sugg),
        "match_levels": levels,
        "estimate_total": total,
        "tax_rate": rate,
        "estimate_total_ex_tax": total_ex,
        "estimate_tax_amount": total_tax,
        "estimate_total_inc_tax": total_inc,
        "next_layers": [r.get("layer_name", "") for r in needs],
    }


def _review_flag(row, state) -> str:
    s = state["suggestions_by_layer"].get(row.get("layer_name", ""))
    if s and s.get("needs_review") == "true":
        return "true"
    return "true" if _needs_price(row) else "false"


# ============================================================
# レイヤー詳細
# ============================================================

def candidate_warnings(c: dict) -> list[str]:
    """候補（suggestion or summary行）の警告を列挙。"""
    w = []
    if c.get("candidate_class") == "processed_item" or c.get("usable_as_base_price") == "false":
        w.append("加工品候補：生材単価に使用しない")
    if c.get("needs_review") == "true":
        w.append("要確認(needs_review)")
    if c.get("warning"):
        w.append(c["warning"])
    if str(c.get("sample_count", "")) == "1":
        w.append("サンプル1件のみ")
    if c.get("match_level") in ("category_only", "none"):
        w.append(f"一致レベル={c.get('match_level')}")
    return w


def extra_candidates(state: dict, material_category: str, show_processed: bool = False,
                     limit: int = 5) -> list[dict]:
    """同一カテゴリの候補単価を summary から数件（優先: 最新→サンプル数）。"""
    cands = [c for c in state["candidates"] if c.get("material_category") == material_category]
    if not show_processed:
        cands = [c for c in cands if c.get("usable_as_base_price") == "true"]
    cands = sorted(
        cands,
        key=lambda c: (c.get("latest_quote_date") or "", cu.to_int(c.get("sample_count")) or 0),
        reverse=True,
    )
    out = []
    for c in cands[:limit]:
        d = dict(c)
        d["_warnings"] = candidate_warnings(c)
        out.append(d)
    return out


def pricing_view(row: dict, tax_rate=tx.DEFAULT_TAX_RATE) -> dict:
    """価格レンジ・pricing_mode の表示用データ（税抜/税込併記）。"""
    from . import layer_mapping as _lm
    resolved = _lm.resolve_pricing(row) or {}
    return {
        "pricing_mode": (row.get("pricing_mode", "") or ""),
        "modes": list(_lm.PRICING_MODES),
        "manual_unit_price": row.get("manual_unit_price", ""),
        "selected": tx.tax_view(resolved.get("selected") if resolved else row.get("unit_price"), tax_rate),
        "recommended": tx.tax_view(row.get("recommended_unit_price"), tax_rate),
        "conservative": tx.tax_view(row.get("conservative_unit_price"), tax_rate),
        "selected_price_basis": resolved.get("basis", "") if resolved else "",
        "price_range_source": row.get("price_range_source", ""),
    }


def layer_detail(state: dict, layer_name: str, show_processed: bool = False,
                 tax_rate=tx.DEFAULT_TAX_RATE) -> dict:
    row = next((r for r in state["mapping_rows"] if r.get("layer_name", "") == layer_name), None)
    summary = state["summary_by_layer"].get(layer_name, {})
    suggestion = state["suggestions_by_layer"].get(layer_name)
    sugg_view = None
    if suggestion:
        sugg_view = dict(suggestion)
        sugg_view["_warnings"] = candidate_warnings(suggestion)
    cat = (row or {}).get("material_category", "")
    return {
        "row": row,
        "summary": summary,
        "suggestion": sugg_view,
        "extra_candidates": extra_candidates(state, cat, show_processed) if cat else [],
        "show_processed": show_processed,
        "pricing": pricing_view(row, tax_rate) if row else None,
    }


# ============================================================
# 候補のフォーム反映（保存しない）
# ============================================================

def apply_candidate_to_row(row: dict, cand: dict) -> dict:
    """候補単価を編集中の行へ反映した新しい row dict を返す（ファイル保存はしない）。"""
    new = dict(row)
    price = cand.get("suggested_unit_price") or cand.get("latest_unit_price") or ""
    unit = cand.get("suggested_price_unit") or cand.get("price_unit") or ""
    vendor = cand.get("suggested_vendor") or cand.get("vendor_name") or ""
    qd = cand.get("suggested_quote_date") or cand.get("latest_quote_date") or ""
    spec_key = cand.get("suggested_spec_key") or cand.get("spec_key") or ""
    new["unit_price"] = str(price)
    if unit:
        new["price_unit"] = unit
    new["price_source"] = f"候補単価:{vendor}".strip(":")
    note_add = f"候補反映 spec_key={spec_key} ({qd})"
    warns = candidate_warnings(cand)
    if warns:
        note_add += " ⚠" + "/".join(warns)
    new["notes"] = (f"{row.get('notes','')}; {note_add}").strip("; ") if row.get("notes") else note_add
    return new


def selection_meta(cand: dict) -> dict:
    return {
        "selected_spec_key": cand.get("suggested_spec_key") or cand.get("spec_key") or "",
        "selected_vendor": cand.get("suggested_vendor") or cand.get("vendor_name") or "",
        "selected_quote_date": cand.get("suggested_quote_date") or cand.get("latest_quote_date") or "",
        "match_level": cand.get("match_level", ""),
        "confidence": cand.get("confidence", ""),
    }


# ============================================================
# 保存・バックアップ・ログ
# ============================================================

def save_approved(out_dir: str, working_rows: list[dict], baseline_rows: list[dict],
                  selections: dict | None = None, now_str: str = "") -> dict:
    """approved を保存。既存があればバックアップ。差分を承認ログに追記。

    戻り: {approved_path, backup_path, logged}
    """
    os.makedirs(out_dir, exist_ok=True)
    approved_path = os.path.join(out_dir, APPROVED_NAME)
    backup_path = None
    if os.path.exists(approved_path):
        ts = (now_str or "").replace("-", "").replace(":", "").replace(" ", "_") or "backup"
        backup_path = os.path.join(out_dir, f"layer_mapping_approved_backup_{ts}.csv")
        shutil.copy2(approved_path, backup_path)

    lmap.write_mapping(approved_path, working_rows)

    # 差分ログ（unit_price または price_unit が変わった行）
    base_by = {r.get("layer_name", ""): r for r in baseline_rows}
    selections = selections or {}
    log_rows = []
    for r in working_rows:
        name = r.get("layer_name", "")
        old = base_by.get(name, {})
        old_up = (old.get("unit_price", "") or "").strip()
        new_up = (r.get("unit_price", "") or "").strip()
        old_pu = (old.get("price_unit", "") or "").strip()
        new_pu = (r.get("price_unit", "") or "").strip()
        if old_up == new_up and old_pu == new_pu:
            continue
        sel = selections.get(name, {})
        log_rows.append({
            "timestamp": now_str,
            "layer_name": name,
            "old_unit_price": old_up,
            "new_unit_price": new_up,
            "old_price_unit": old_pu,
            "new_price_unit": new_pu,
            "selected_spec_key": sel.get("selected_spec_key", ""),
            "selected_vendor": sel.get("selected_vendor", ""),
            "selected_quote_date": sel.get("selected_quote_date", ""),
            "match_level": sel.get("match_level", ""),
            "confidence": sel.get("confidence", ""),
            "note": r.get("notes", ""),
        })

    _append_log(out_dir, log_rows)
    return {"approved_path": approved_path, "backup_path": backup_path, "logged": len(log_rows)}


def _append_log(out_dir: str, log_rows: list[dict]) -> None:
    if not log_rows:
        return
    import csv
    log_path = os.path.join(out_dir, LOG_NAME)
    exists = os.path.exists(log_path)
    with open(log_path, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=APPROVAL_LOG_FIELDS, extrasaction="ignore")
        if not exists:
            w.writeheader()
        for r in log_rows:
            w.writerow(r)


def rerun_command(out_dir: str) -> str:
    """保存後に実行するCLIコマンド文字列（UI表示用）。"""
    return (
        "python -m steel_estimator.cli run-rhino-estimate "
        f"--rhino-csv {os.path.join(out_dir, 'rhino_objects.csv')} "
        f"--mapping {os.path.join(out_dir, APPROVED_NAME)} "
        f"--cost-items {os.path.join(out_dir, 'cost_items.csv')} "
        f"--out-dir {out_dir}"
    )
