"""東鋼材PDF単価DBから「候補単価マスター」を生成する。

PDF DBには生材・型切・曲げ・丸切・窓枠・H形鋼などが混在するため、そのまま
Rhino見積の単価候補にすると危険（加工費込み単価が生材単価を汚染する）。
ここで candidate_class（生材/板材/加工品/JIS要マスター/不明）に分類し、生材単価と
加工品単価を分離したうえで、根拠（PDF・見積日・業者・信頼度・レビュー要否）を必ず残す。

自動確定はしない。あくまで人間が選ぶための「候補提示」。
"""

from __future__ import annotations

import statistics

from . import csv_utils as cu
from .models import MaterialCategory as C


# 生材候補から除外すべき加工・外注を示す語（含まれたら processed_item へ退避）
PROCESSED_KEYWORDS = (
    "曲げ", "R曲げ", "L曲げ", "3方曲げ", "型切", "丸切", "切板", "窓枠", "枠",
    "溶接", "加工", "孔", "穴", "レーザー", "シャーリング", "曲", "巻", "ロール",
    "多分割", "組立", "製作", "一式",
)

# candidate_class
CLASS_BASE = "base_material"
CLASS_PLATE = "plate_material"
CLASS_PROCESSED = "processed_item"
CLASS_JIS = "jis_shape_needs_master"
CLASS_UNKNOWN = "unknown"

_BASE_CATEGORIES = (
    C.ROUND_PIPE, C.SQUARE_PIPE, C.FLAT_BAR, C.ROUND_BAR, C.SQUARE_BAR, C.ANGLE,
)
_JIS_CATEGORIES = (C.H_BEAM, C.CHANNEL)

CANDIDATE_FIELDS = (
    "vendor_name", "material_category", "material_grade", "spec_key", "spec_text",
    "normalized_spec", "price_type", "unit_price", "price_unit", "amount", "quantity",
    "quote_date", "source_pdf", "source_page", "confidence", "usable_as_base_price",
    "candidate_class", "needs_review", "warning", "notes",
)

SUMMARY_FIELDS = (
    "vendor_name", "material_category", "material_grade", "spec_key", "normalized_spec",
    "candidate_class", "latest_unit_price", "latest_quote_date", "median_unit_price",
    "average_unit_price", "min_unit_price", "max_unit_price", "sample_count",
    "latest_source_pdf", "price_unit", "confidence", "usable_as_base_price",
    "needs_review", "warning", "notes",
)


def _g(v):
    """数値を簡潔な文字列に（48.6→'48.6', 6000.0→'6000'）。None→''。"""
    if v is None or v == "":
        return ""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return f"{f:g}"


# ============================================================
# 分類
# ============================================================

def is_processed(text: str) -> bool:
    t = text or ""
    return any(kw in t for kw in PROCESSED_KEYWORDS)


def classify(rec: dict) -> str:
    category = rec.get("material_category", "") or ""
    text = " ".join(str(rec.get(k, "") or "") for k in
                    ("item_name_original", "raw_text_line", "notes", "shape_token"))
    if category in _JIS_CATEGORIES:
        return CLASS_JIS
    if is_processed(text):
        return CLASS_PROCESSED
    if category == C.PLATE:
        return CLASS_PLATE
    if category in _BASE_CATEGORIES:
        return CLASS_BASE
    return CLASS_UNKNOWN


# ============================================================
# 正規化キー
# ============================================================

def build_spec(rec: dict) -> tuple[str, str, bool]:
    """(normalized_spec, spec_key, missing_dims) を返す。

    spec_key = 'category|grade|tok1|tok2|...'、normalized_spec = 'grade_tok1_tok2_...'。
    寸法が欠ける場合は token を省き missing_dims=True。
    """
    cat = rec.get("material_category", "") or "unknown"
    grade = (rec.get("material_grade", "") or "").upper()
    d = cu.to_float(rec.get("diameter_mm"))
    t = cu.to_float(rec.get("thickness_mm"))
    w = cu.to_float(rec.get("width_mm"))
    h = cu.to_float(rec.get("height_mm"))
    L = cu.to_float(rec.get("length_mm"))
    pw = cu.to_float(rec.get("plate_width_mm"))
    ph = cu.to_float(rec.get("plate_height_mm"))

    toks: list[str] = []
    missing = False

    def need(val, tok):
        nonlocal missing
        if val is None:
            missing = True
        else:
            toks.append(tok)

    if cat == C.ROUND_PIPE or cat == C.ROLLED:
        need(d, f"D{_g(d)}"); need(t, f"t{_g(t)}"); need(L, f"L{_g(L)}")
    elif cat == C.ROUND_BAR:
        need(d, f"D{_g(d)}"); need(L, f"L{_g(L)}")
    elif cat in (C.SQUARE_PIPE, C.ANGLE, C.CHANNEL, C.H_BEAM):
        if w is not None and h is not None:
            toks.append(f"{_g(w)}x{_g(h)}")
        else:
            missing = True
        need(t, f"t{_g(t)}"); need(L, f"L{_g(L)}")
    elif cat == C.FLAT_BAR:
        need(t, f"t{_g(t)}"); need(w, f"W{_g(w)}"); need(L, f"L{_g(L)}")
    elif cat == C.PLATE:
        need(t, f"t{_g(t)}")
        if pw is not None and ph is not None:
            toks.append(f"{_g(pw)}x{_g(ph)}")
    else:  # unknown / square_bar 等
        for val, pre in ((d, "D"), (t, "t"), (w, "W"), (h, "H"), (L, "L")):
            if val is not None:
                toks.append(f"{pre}{_g(val)}")

    spec_key = "|".join([cat, grade] + toks)
    # plate は normalized_spec のみ 'PL' を含める（spec_key には含めない）
    norm_tokens = (["PL"] + toks) if cat == C.PLATE else toks
    normalized_spec = "_".join(([grade] if grade else []) + norm_tokens)
    return normalized_spec, spec_key, missing


def parse_spec_key(spec_key: str) -> dict:
    """spec_key を {category, grade, diameter, thickness, width, height, length} に分解。"""
    out = {"category": "", "grade": "", "diameter": None, "thickness": None,
           "width": None, "height": None, "length": None}
    if not spec_key:
        return out
    parts = spec_key.split("|")
    if parts:
        out["category"] = parts[0]
    if len(parts) > 1:
        out["grade"] = parts[1]
    for tok in parts[2:]:
        if "x" in tok and not tok.startswith(("D", "t", "L", "W", "H")):
            a, _, b = tok.partition("x")
            out["width"] = cu.to_float(a)
            out["height"] = cu.to_float(b)
        elif tok.startswith("D"):
            out["diameter"] = cu.to_float(tok[1:])
        elif tok.startswith("t"):
            out["thickness"] = cu.to_float(tok[1:])
        elif tok.startswith("W"):
            out["width"] = cu.to_float(tok[1:])
        elif tok.startswith("H"):
            out["height"] = cu.to_float(tok[1:])
        elif tok.startswith("L"):
            out["length"] = cu.to_float(tok[1:])
    return out


# ============================================================
# 信頼度 / 使用可否
# ============================================================

_CLASS_CONF = {
    CLASS_BASE: 0.9, CLASS_PLATE: 0.7, CLASS_JIS: 0.4,
    CLASS_PROCESSED: 0.3, CLASS_UNKNOWN: 0.2,
}


def _usable_as_base(cclass: str) -> bool:
    return cclass in (CLASS_BASE, CLASS_PLATE)


# ============================================================
# 候補行の生成
# ============================================================

def build_candidates(records: list[dict], vendor: str = "") -> tuple[list[dict], list[str]]:
    """抽出レコード群から候補単価行を作る。戻り: (candidate_rows, warnings)。"""
    warnings: list[str] = []
    rows = []
    matched = 0
    for rec in records:
        vn = rec.get("vendor_name", "") or ""
        if vendor and vendor.lower() not in vn.lower():
            continue
        matched += 1
        cclass = classify(rec)
        normalized_spec, spec_key, missing = build_spec(rec)
        rec_review = str(rec.get("needs_review", "")).strip() in ("1", "true", "True")
        needs_review = rec_review or missing or cclass in (CLASS_PROCESSED, CLASS_UNKNOWN, CLASS_JIS)
        warn = []
        if missing:
            warn.append("寸法欠落のためspec_key不完全")
        if cclass == CLASS_PROCESSED:
            warn.append("加工品: 生材単価として使用不可")
        if cclass == CLASS_JIS:
            warn.append("JIS規格表/重量表が必要")

        rows.append({
            "vendor_name": vn,
            "material_category": rec.get("material_category", ""),
            "material_grade": rec.get("material_grade", ""),
            "spec_key": spec_key,
            "spec_text": rec.get("item_name_original", "") or rec.get("dimension_text_original", ""),
            "normalized_spec": normalized_spec,
            "price_type": _price_type(cclass),
            "unit_price": _g(rec.get("unit_price")),
            "price_unit": rec.get("unit", "") or "個",
            "amount": _g(rec.get("amount")),
            "quantity": _g(rec.get("quantity")),
            "quote_date": rec.get("quote_date", ""),
            "source_pdf": rec.get("source_pdf_filename", ""),
            "source_page": rec.get("page_number", ""),
            "confidence": round(_CLASS_CONF.get(cclass, 0.2), 2),
            "usable_as_base_price": "true" if _usable_as_base(cclass) else "false",
            "candidate_class": cclass,
            "needs_review": "true" if needs_review else "false",
            "warning": "; ".join(warn),
            "notes": rec.get("notes", ""),
        })
    if vendor and matched == 0:
        warnings.append(f"vendor '{vendor}' に一致するレコードが0件。vendor_nameを確認してください。")
    return rows, warnings


def _price_type(cclass: str) -> str:
    if cclass in (CLASS_BASE, CLASS_PLATE):
        return "material"
    if cclass == CLASS_PROCESSED:
        return "processed"
    if cclass == CLASS_JIS:
        return "needs_master"
    return "unknown"


# ============================================================
# 集約
# ============================================================

def aggregate(candidate_rows: list[dict]) -> list[dict]:
    """spec_key 単位で単価を集約し、外れ値warningを付ける。"""
    groups: dict[str, list[dict]] = {}
    for r in candidate_rows:
        groups.setdefault(r["spec_key"], []).append(r)

    out = []
    for spec_key, members in groups.items():
        priced = [(cu.to_float(m["unit_price"]), m) for m in members]
        priced = [(p, m) for p, m in priced if p is not None]
        prices = [p for p, _ in priced]
        latest = max(members, key=lambda m: m.get("quote_date") or "")
        latest_price = cu.to_float(latest["unit_price"])

        if prices:
            median = statistics.median(prices)
            avg = statistics.fmean(prices)
            pmin, pmax = min(prices), max(prices)
        else:
            median = avg = pmin = pmax = None

        warn = []
        if prices and pmin and pmin > 0 and pmax / pmin >= 2.0:
            warn.append(f"価格レンジが広い(max/min={pmax/pmin:.1f})")
        if latest_price and median and median > 0 and abs(latest_price - median) / median >= 0.5:
            warn.append("最新単価が中央値から50%以上乖離")
        if len(members) == 1:
            warn.append("サンプル1件のみ")
        if any(m["needs_review"] == "true" for m in members):
            warn.append("要確認レコードを含む")

        cclass = _majority(m["candidate_class"] for m in members)
        needs_review = bool(warn) or cclass in (CLASS_PROCESSED, CLASS_UNKNOWN, CLASS_JIS)
        out.append({
            "vendor_name": latest["vendor_name"],
            "material_category": latest["material_category"],
            "material_grade": latest["material_grade"],
            "spec_key": spec_key,
            "normalized_spec": latest["normalized_spec"],
            "candidate_class": cclass,
            "latest_unit_price": _g(latest_price),
            "latest_quote_date": latest.get("quote_date", ""),
            "median_unit_price": _g(median),
            "average_unit_price": _g(round(avg, 1) if avg is not None else None),
            "min_unit_price": _g(pmin),
            "max_unit_price": _g(pmax),
            "sample_count": len(members),
            "latest_source_pdf": latest.get("source_pdf", ""),
            "price_unit": latest.get("price_unit", "個"),
            "confidence": latest.get("confidence", 0.2),
            "usable_as_base_price": "true" if _usable_as_base(cclass) else "false",
            "needs_review": "true" if needs_review else "false",
            "warning": "; ".join(warn),
            "notes": "",
        })
    out.sort(key=lambda r: (r["material_category"], r["spec_key"]))
    return out


def _majority(values) -> str:
    counts: dict[str, int] = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    return max(counts.items(), key=lambda kv: kv[1])[0] if counts else CLASS_UNKNOWN


# ============================================================
# レポート
# ============================================================

def build_report(candidate_rows: list[dict], summary_rows: list[dict],
                 vendor: str, now_str: str = "") -> str:
    by_class: dict[str, int] = {}
    by_cat: dict[str, int] = {}
    for r in candidate_rows:
        by_class[r["candidate_class"]] = by_class.get(r["candidate_class"], 0) + 1
        by_cat[r["material_category"]] = by_cat.get(r["material_category"], 0) + 1
    needs_review = sum(1 for r in candidate_rows if r["needs_review"] == "true")

    base_examples = [r for r in candidate_rows if r["candidate_class"] == CLASS_BASE][:5]
    proc_examples = [r for r in candidate_rows if r["candidate_class"] == CLASS_PROCESSED][:5]
    outliers = [s for s in summary_rows if s["warning"]][:8]

    lines = [
        "# 東鋼材 候補単価レポート",
        "",
        f"- vendor: {vendor or '(全件)'}",
    ]
    if now_str:
        lines.append(f"- 実行: {now_str}")
    lines += [
        f"- 抽出対象レコード数: {len(candidate_rows)}",
        f"- spec_key集約数: {len(summary_rows)}",
        f"- needs_review件数: {needs_review}",
        "",
        "## candidate_class 別件数",
        f"- base_material: {by_class.get(CLASS_BASE, 0)}",
        f"- plate_material: {by_class.get(CLASS_PLATE, 0)}",
        f"- processed_item: {by_class.get(CLASS_PROCESSED, 0)}",
        f"- jis_shape_needs_master: {by_class.get(CLASS_JIS, 0)}",
        f"- unknown: {by_class.get(CLASS_UNKNOWN, 0)}",
        "",
        "## カテゴリ別件数",
    ]
    for cat, n in sorted(by_cat.items(), key=lambda kv: -kv[1]):
        lines.append(f"- {cat}: {n}")
    lines += ["", "## 最新単価の代表例（生材）"]
    for r in base_examples:
        lines.append(f"- {r['normalized_spec']} : ¥{r['unit_price']} "
                     f"({r['quote_date']} {r['source_pdf']})")
    if not base_examples:
        lines.append("- なし")
    lines += ["", "## 生材候補から除外した加工品の代表例（processed_item）"]
    for r in proc_examples:
        lines.append(f"- {r['spec_text']} : ¥{r['unit_price']} → 生材単価に使用しない")
    if not proc_examples:
        lines.append("- なし")
    lines += ["", "## 外れ値候補（要確認）"]
    for s in outliers:
        lines.append(f"- {s['normalized_spec']}: {s['warning']} "
                     f"(latest ¥{s['latest_unit_price']}, n={s['sample_count']})")
    if not outliers:
        lines.append("- なし")
    lines += [
        "",
        "## Rhino見積で使う際の注意",
        "- 第一候補は latest_unit_price。ただし warning がある spec_key は人間が確認する。",
        "- processed_item / jis_shape_needs_master は生材単価として使わない。",
        "- 候補は自動確定せず、layer_mapping への反映は人間が行う。",
        "",
        "## 次に人間が確認すべきCSV",
        "1. `toko_candidate_prices.csv`（明細・分類）",
        "2. `toko_candidate_price_summary.csv`（spec_key別の集約・第一候補）",
        "3. `layer_mapping_price_suggestions.csv`（mappingへの提案）",
    ]
    return "\n".join(lines) + "\n"


# ============================================================
# I/O
# ============================================================

def load_records_from_db(db_path: str) -> list[dict]:
    from . import database as db
    conn = db.connect(db_path)
    rows = db.fetch_all(conn)
    conn.close()
    return rows


def load_records_from_csv(csv_path: str) -> list[dict]:
    return cu.read_dicts(csv_path)


def write_candidates(path: str, rows: list[dict]) -> int:
    return cu.write_dicts(path, CANDIDATE_FIELDS, rows)


def write_summary(path: str, rows: list[dict]) -> int:
    return cu.write_dicts(path, SUMMARY_FIELDS, rows)
