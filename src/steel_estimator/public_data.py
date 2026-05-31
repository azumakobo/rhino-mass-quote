"""公開用の匿名化・集約・丸め済み参考単価データ（Phase RC1.1）。

方針:
  - 実取引データ（取引先名・見積日・PDF名・source_page・個別明細・実数量・実金額）は
    公開しない。
  - 板厚別・鋼材種別別に集約した「概算見積用の丸め済み参考値」だけを公開する。
  - 価格は 10円単位で切り上げ（安全側）。
  - 出力は public_reference_data/ に置き、Git管理してよい（中身は匿名化済みのみ）。

このモジュールは price_ranges.py が作る range master（実データ由来）を入力に、
公開可能な集約CSVへ変換する。逆変換（個別明細への復元）はできない。
"""

from __future__ import annotations

import os
import re
import statistics

from . import csv_utils as cu
from . import settings as tx
from . import price_analysis as pa
from . import price_ranges as pr
from . import layer_mapping as lmap
from .models import MaterialCategory as C


PUBLIC_WARNING = "切板・型切由来の外接矩形ベース参考価格。実取引価格ではなく概算用。"
SHAPE_WARNING = "過去見積から集約・丸めた参考価格。実取引価格ではなく概算用。"

# 公開CSVに含めてはいけない列名（audit用）
FORBIDDEN_HEADERS = {
    "vendor_name", "quote_date", "latest_quote_date", "source_pdf", "source_page",
    "spec_key", "amount", "quantity", "unit_price", "latest_unit_price",
    "median_unit_price", "average_unit_price", "min_unit_price", "max_unit_price",
}
# 公開CSV/MDに含めてはいけない値パターン（取引先・PDF・日付）
FORBIDDEN_VALUE_RES = [
    (re.compile(r"\.pdf", re.IGNORECASE), "PDFファイル名"),
    (re.compile(r"\d{4}-\d{2}-\d{2}"), "日付(見積日)"),
    (re.compile(r"東鋼材"), "取引先名"),
    (re.compile(r"秋山"), "取引先名"),
    (re.compile(r"akiyama", re.IGNORECASE), "取引先名"),
]

_PLATE_PRIO = {"raw_plate": 0, "rectangular_cut_plate": 1,
               "shaped_cut_plate": 2, "bent_plate": 3, "unknown_plate": 4}


PUBLIC_PLATE_FIELDS = (
    "material_category", "material_grade", "thickness_mm", "reference_basis",
    "sample_count_band",
    "recommended_price_per_kg_ex_tax_rounded", "conservative_price_per_kg_ex_tax_rounded",
    "recommended_price_per_kg_inc_tax_rounded", "conservative_price_per_kg_inc_tax_rounded",
    "recommended_price_per_m2_ex_tax_rounded", "conservative_price_per_m2_ex_tax_rounded",
    "recommended_price_per_m2_inc_tax_rounded", "conservative_price_per_m2_inc_tax_rounded",
    "pricing_mode_default", "editable", "confidence_band", "warning", "notes",
)

PUBLIC_SHAPE_FIELDS = (
    "material_category", "material_grade", "display_spec", "shape_group",
    "diameter_mm", "width_mm", "height_mm", "thickness_mm", "stock_length_mm",
    "sample_count_band",
    "recommended_unit_price_ex_tax_rounded", "conservative_unit_price_ex_tax_rounded",
    "recommended_unit_price_inc_tax_rounded", "conservative_unit_price_inc_tax_rounded",
    "recommended_price_per_m_ex_tax_rounded", "conservative_price_per_m_ex_tax_rounded",
    "recommended_price_per_m_inc_tax_rounded", "conservative_price_per_m_inc_tax_rounded",
    "recommended_price_per_kg_ex_tax_rounded", "conservative_price_per_kg_ex_tax_rounded",
    "recommended_price_per_kg_inc_tax_rounded", "conservative_price_per_kg_inc_tax_rounded",
    "pricing_mode_default", "editable", "confidence_band", "warning", "notes",
)


# ============================================================
# 帯（band）化
# ============================================================

def sample_count_band(n) -> str:
    n = cu.to_int(n) or 0
    if n >= 21:
        return "21+"
    if n >= 6:
        return "6-20"
    if n >= 2:
        return "2-5"
    return "1"


def confidence_band(c) -> str:
    f = cu.to_float(c)
    if f is None:
        return "low"
    if f < 0.4:
        return "low"
    if f < 0.7:
        return "medium"
    return "high"


def _f(v):
    return cu.to_float(v)


def _pair(ex_val, rate, unit):
    """税抜値 → (税抜丸め, 税込丸め)。空なら ('','')。"""
    if ex_val in (None, ""):
        return ("", "")
    return tx.public_price(ex_val, rate, unit)


# ============================================================
# 板材の公開参考価格
# ============================================================

def build_public_plate(plate_range_rows: list[dict],
                       tax_rate: float = tx.DEFAULT_TAX_RATE,
                       unit: int = tx.DEFAULT_PUBLIC_ROUND_UNIT) -> list[dict]:
    rate = tx.normalize_rate(tax_rate)
    # (grade, thickness) ごとに、最も信頼できる plate_class を代表に採る
    groups: dict[tuple, list[dict]] = {}
    for r in plate_range_rows:
        groups.setdefault((r.get("material_grade", ""), r.get("thickness_mm", "")), []).append(r)

    out = []
    for (grade, thick), members in groups.items():
        best = min(members, key=lambda r: _PLATE_PRIO.get(r.get("plate_class", ""), 9))
        n = best.get("sample_count", "")
        kg_rec = _pair(best.get("recommended_price_per_kg_ex_tax"), rate, unit)
        kg_con = _pair(best.get("conservative_price_per_kg_ex_tax"), rate, unit)
        m2_rec = _pair(best.get("median_price_per_m2_ex_tax"), rate, unit)
        # per_m2 の安全側も中央値×1.3〜2.0にclamp（外れ値抑制。kg等と整合）
        _m2_safe = pr.safe_conservative(_f(best.get("median_price_per_m2_ex_tax")),
                                        _f(best.get("max_price_per_m2_ex_tax")))
        m2_con = _pair(_m2_safe, rate, unit)
        band = sample_count_band(n)
        basis = "insufficient_data" if band == "1" else "cut_or_shaped_plate_bounding_box"
        out.append({
            "material_category": C.PLATE,
            "material_grade": grade,
            "thickness_mm": thick,
            "reference_basis": basis,
            "sample_count_band": band,
            "recommended_price_per_kg_ex_tax_rounded": kg_rec[0],
            "conservative_price_per_kg_ex_tax_rounded": kg_con[0],
            "recommended_price_per_kg_inc_tax_rounded": kg_rec[1],
            "conservative_price_per_kg_inc_tax_rounded": kg_con[1],
            "recommended_price_per_m2_ex_tax_rounded": m2_rec[0],
            "conservative_price_per_m2_ex_tax_rounded": m2_con[0],
            "recommended_price_per_m2_inc_tax_rounded": m2_rec[1],
            "conservative_price_per_m2_inc_tax_rounded": m2_con[1],
            "pricing_mode_default": "median",
            "editable": "true",
            "confidence_band": confidence_band(best.get("confidence")),
            "warning": PUBLIC_WARNING,
            "notes": "板厚別に集約・10円単位切り上げ済み。手入力変更可。",
        })
    out.sort(key=lambda r: (_f(r["thickness_mm"]) or 0, r["material_grade"]))
    return out


def write_public_plate(path: str, rows: list[dict]) -> int:
    return cu.write_dicts(path, PUBLIC_PLATE_FIELDS, rows)


# ============================================================
# 鋼材種別の公開参考価格
# ============================================================

def _display_spec(cat, parsed) -> str:
    label = pa.JP_LABEL.get(cat, cat)
    d, w, h, t = (parsed.get("diameter_mm"), parsed.get("width_mm"),
                  parsed.get("height_mm"), parsed.get("thickness_mm"))
    if cat == C.FLAT_BAR:
        return f"FB {w}x{t}".replace("Nonex", "").strip()
    bits = []
    if d:
        bits.append(f"D{d}")
    if w and h:
        bits.append(f"{w}x{h}")
    elif w:
        bits.append(f"W{w}")
    if t:
        bits.append(f"t{t}")
    return (label + " " + " ".join(bits)).strip()


def build_public_shape(shape_range_rows: list[dict],
                       tax_rate: float = tx.DEFAULT_TAX_RATE,
                       unit: int = tx.DEFAULT_PUBLIC_ROUND_UNIT) -> list[dict]:
    rate = tx.normalize_rate(tax_rate)
    # (category, grade, dims) ごとに、定尺（最長 stock_length）を代表に採る
    groups: dict[tuple, list[dict]] = {}
    for r in shape_range_rows:
        key = (r.get("material_category", ""), r.get("material_grade", ""),
               r.get("diameter_mm", ""), r.get("width_mm", ""),
               r.get("height_mm", ""), r.get("thickness_mm", ""))
        groups.setdefault(key, []).append(r)

    out = []
    for key, members in groups.items():
        rep = max(members, key=lambda r: (_f(r.get("stock_length_mm")) or 0,
                                          cu.to_int(r.get("sample_count")) or 0))
        cat, grade = key[0], key[1]
        parsed = {"diameter_mm": key[2], "width_mm": key[3],
                  "height_mm": key[4], "thickness_mm": key[5]}
        up = (_pair(rep.get("recommended_unit_price_ex_tax"), rate, unit),
              _pair(rep.get("conservative_unit_price_ex_tax"), rate, unit))
        pm = (_pair(rep.get("recommended_price_per_m_ex_tax"), rate, unit),
              _pair(rep.get("conservative_price_per_m_ex_tax"), rate, unit))
        pk = (_pair(rep.get("recommended_price_per_kg_ex_tax"), rate, unit),
              _pair(rep.get("conservative_price_per_kg_ex_tax"), rate, unit))
        out.append({
            "material_category": cat,
            "material_grade": grade,
            "display_spec": _display_spec(cat, parsed),
            "shape_group": pa.JP_LABEL.get(cat, cat),
            "diameter_mm": key[2], "width_mm": key[3], "height_mm": key[4],
            "thickness_mm": key[5], "stock_length_mm": rep.get("stock_length_mm", ""),
            "sample_count_band": sample_count_band(rep.get("sample_count")),
            "recommended_unit_price_ex_tax_rounded": up[0][0],
            "conservative_unit_price_ex_tax_rounded": up[1][0],
            "recommended_unit_price_inc_tax_rounded": up[0][1],
            "conservative_unit_price_inc_tax_rounded": up[1][1],
            "recommended_price_per_m_ex_tax_rounded": pm[0][0],
            "conservative_price_per_m_ex_tax_rounded": pm[1][0],
            "recommended_price_per_m_inc_tax_rounded": pm[0][1],
            "conservative_price_per_m_inc_tax_rounded": pm[1][1],
            "recommended_price_per_kg_ex_tax_rounded": pk[0][0],
            "conservative_price_per_kg_ex_tax_rounded": pk[1][0],
            "recommended_price_per_kg_inc_tax_rounded": pk[0][1],
            "conservative_price_per_kg_inc_tax_rounded": pk[1][1],
            "pricing_mode_default": "median",
            "editable": "true",
            "confidence_band": confidence_band(rep.get("confidence")),
            "warning": SHAPE_WARNING,
            "notes": "種別・寸法別に集約・10円単位切り上げ済み。手入力変更可。",
        })
    out.sort(key=lambda r: (r["material_category"], r["display_spec"]))
    return out


def write_public_shape(path: str, rows: list[dict]) -> int:
    return cu.write_dicts(path, PUBLIC_SHAPE_FIELDS, rows)


# ============================================================
# 公開→見積用 range 形式へのアダプタ（fallback利用）
# ============================================================

def public_plate_to_range(public_rows: list[dict]) -> list[dict]:
    out = []
    for r in public_rows:
        out.append({
            "material_grade": r.get("material_grade", ""),
            "thickness_mm": r.get("thickness_mm", ""),
            "plate_class": "public_reference",
            "recommended_price_per_kg_ex_tax": r.get("recommended_price_per_kg_ex_tax_rounded", ""),
            "conservative_price_per_kg_ex_tax": r.get("conservative_price_per_kg_ex_tax_rounded", ""),
        })
    return out


def public_shape_to_range(public_rows: list[dict]) -> list[dict]:
    out = []
    for r in public_rows:
        out.append({
            "material_category": r.get("material_category", ""),
            "material_grade": r.get("material_grade", ""),
            "diameter_mm": r.get("diameter_mm", ""),
            "width_mm": r.get("width_mm", ""),
            "height_mm": r.get("height_mm", ""),
            "thickness_mm": r.get("thickness_mm", ""),
            "spec_key": "public_reference",
            "recommended_unit_price_ex_tax": r.get("recommended_unit_price_ex_tax_rounded", ""),
            "conservative_unit_price_ex_tax": r.get("conservative_unit_price_ex_tax_rounded", ""),
            "recommended_price_per_m_ex_tax": r.get("recommended_price_per_m_ex_tax_rounded", ""),
            "conservative_price_per_m_ex_tax": r.get("conservative_price_per_m_ex_tax_rounded", ""),
            "recommended_price_per_kg_ex_tax": r.get("recommended_price_per_kg_ex_tax_rounded", ""),
            "conservative_price_per_kg_ex_tax": r.get("conservative_price_per_kg_ex_tax_rounded", ""),
        })
    return out


# ============================================================
# notes Markdown
# ============================================================

def build_notes_md(plate_rows, shape_rows, tax_rate, unit) -> str:
    rate = tx.normalize_rate(tax_rate)
    L = [
        "# 公開用 参考単価データ について",
        "",
        f"- 丸め単位: {unit}円（**切り上げ**＝安全側）  / 税率: {rate:.0%}",
        f"- 板材参考: {len(plate_rows)}件 / 鋼材参考: {len(shape_rows)}件",
        "",
        "## これは何か",
        "- 過去見積から **匿名化・集約・10円単位切り上げ** した「概算見積用の参考値」です。",
        "- **実取引価格ではありません。** 取引先名・見積日・PDF名・個別明細・実数量・実金額は含みません。",
        "",
        "## 価格の前提と注意",
        "- 価格は地域・時期・数量・加工条件・材料市況で変動します。",
        "- 板材は切板・型切の外接矩形ベース参考。実形状より重量を過大評価しうる（kg単価は割安方向）。",
        "- `unit_price` は税抜、税込は表示用。数値は UI または CSV で手入力変更できます。",
        "- 通常見積は recommended（中央値）。安全側は conservative＝中央値を基準に"
        "最低1.3倍・最大2.0倍の範囲へ補正した値（外れ値による過大評価を抑制）。",
        "",
        "## 実発注前",
        "- 必ず各業者へ見積を取り直して確認してください。本データは研究・制作初期の概算用です。",
    ]
    return "\n".join(L) + "\n"


def write_notes(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


# ============================================================
# デモ入力（実データ非依存・公開参考価格だけで動かす）
# ============================================================

def _mrow(**kw):
    base = {f: "" for f in lmap.MAPPING_FIELDS}
    base["enabled"] = "true"
    base["waste_rate"] = "1.0"
    base.update(kw)
    return base


def build_demo_inputs():
    """デモ用の layer_summary 相当と layer_mapping を返す（実データ非依存）。"""
    summary = [
        {"layer_name": "デモ::鉄板t6", "total_area_m2": "2.0", "object_count": "3"},
        {"layer_name": "デモ::角パイプ40x40", "total_curve_length_m": "12", "object_count": "4"},
        {"layer_name": "デモ::丸パイプD48.6", "total_curve_length_m": "8", "object_count": "2"},
    ]
    mapping = [
        _mrow(layer_name="デモ::鉄板t6", calc_type=lmap.CALC_AREA_TO_WEIGHT,
              material_category=C.PLATE, material_grade="SS400",
              thickness_mm="6", price_unit="kg", density_g_cm3="7.85"),
        _mrow(layer_name="デモ::角パイプ40x40", calc_type=lmap.CALC_CURVE_TO_METER,
              material_category=C.SQUARE_PIPE, material_grade="SS400",
              width_mm="40", height_mm="40", thickness_mm="2.3", price_unit="m"),
        _mrow(layer_name="デモ::丸パイプD48.6", calc_type=lmap.CALC_CURVE_TO_METER,
              material_category=C.ROUND_PIPE, material_grade="STK400",
              diameter_mm="48.6", thickness_mm="2.3", price_unit="m"),
    ]
    return summary, mapping


# ============================================================
# 公開安全性監査
# ============================================================

def audit_public_dir(public_dir: str, repo_root: str = ".") -> dict:
    """公開ディレクトリのCSV/MDを走査し、禁止列・禁止値が無いか検査する。"""
    issues: list[str] = []
    checked: list[str] = []
    if not os.path.isdir(public_dir):
        return {"ok": False, "issues": [f"公開ディレクトリが存在しません: {public_dir}"],
                "checked": []}

    for name in sorted(os.listdir(public_dir)):
        path = os.path.join(public_dir, name)
        if not os.path.isfile(path):
            continue
        checked.append(name)
        if name.lower().endswith(".csv"):
            rows = cu.read_dicts(path)
            headers = set(rows[0].keys()) if rows else set()
            bad = headers & FORBIDDEN_HEADERS
            if bad:
                issues.append(f"{name}: 禁止列が含まれる: {sorted(bad)}")
            for i, r in enumerate(rows):
                for v in r.values():
                    issues.extend(_scan_value(name, i, v))
        elif name.lower().endswith(".md"):
            with open(path, encoding="utf-8") as f:
                text = f.read()
            for rgx, label in FORBIDDEN_VALUE_RES:
                if rgx.search(text):
                    issues.append(f"{name}: {label}らしき記述: /{rgx.pattern}/")

    issues.extend(_audit_git_safety(repo_root))
    return {"ok": not issues, "issues": issues, "checked": checked}


def _scan_value(name, row_idx, v) -> list[str]:
    out = []
    s = "" if v is None else str(v)
    for rgx, label in FORBIDDEN_VALUE_RES:
        if rgx.search(s):
            out.append(f"{name}[row {row_idx}]: {label}らしき値: {s[:40]!r}")
    return out


def _audit_git_safety(repo_root: str) -> list[str]:
    """data/実データ・credentials が Git管理外であることを確認する。"""
    issues = []
    gi = os.path.join(repo_root, ".gitignore")
    if not os.path.exists(gi):
        return ["[git] .gitignore が無い（data/・credentials の除外を確認できない）"]
    with open(gi, encoding="utf-8") as f:
        gitignore = f.read()
    for needed in ("data/", "credentials.json", "token.json", "*.pdf"):
        if needed not in gitignore:
            issues.append(f"[git] .gitignore に '{needed}' が無い")

    # git管理されているなら、追跡ファイルに実データが無いかも確認
    import subprocess
    try:
        res = subprocess.run(["git", "ls-files"], cwd=repo_root,
                             capture_output=True, text=True, timeout=10)
        if res.returncode == 0:
            tracked = res.stdout.splitlines()
            for f in tracked:
                if f.startswith("data/") or f in ("credentials.json", "token.json") \
                        or f.lower().endswith((".pdf", ".3dm")):
                    issues.append(f"[git] 実データ/機微ファイルが追跡されている: {f}")
        # returncode != 0 → gitリポジトリでない。.gitignoreで担保。
    except (FileNotFoundError, subprocess.SubprocessError):
        pass
    return issues
