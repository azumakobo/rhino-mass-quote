"""東鋼材 候補単価DBの「分析密度」を上げるための分析層（Phase R6）。

目的:
  - 候補単価DB（spec_key別の集約）を、実務で「何がいくらか」を判断できる水準に分析する。
  - 全カテゴリの代表単価・最新・中央値・レンジ・サンプル数・外れ値を一覧化する。
  - 単価単位が「個」しかない現状から、定尺長(spec_keyのL)とJIS式重量で
    price_per_m / price_per_kg を推定する（換算できないものは無理に出さない）。
  - 生材(base_material)と加工品(processed_item)・板材(plate)を混ぜない方針は維持。
    ただし加工品・切板は捨てず「参考」として別表に残す。

自動確定はしない。すべて人間が選ぶための分析・候補提示。
"""

from __future__ import annotations

import statistics

from . import csv_utils as cu
from . import candidate_prices as cp
from . import estimate as est
from . import settings as tx
from .models import MaterialCategory as C, MaterialRequest


# ============================================================
# ラベル・定数
# ============================================================

JP_LABEL = {
    C.ROUND_PIPE: "丸パイプ",
    C.SQUARE_PIPE: "角パイプ",
    C.ANGLE: "アングル",
    C.CHANNEL: "チャンネル",
    C.FLAT_BAR: "FB(フラットバー)",
    C.PLATE: "鋼板",
    C.ROUND_BAR: "丸棒",
    C.SQUARE_BAR: "角棒",
    C.H_BEAM: "H形鋼",
    C.ROLLED: "ロール材",
    C.UNKNOWN: "不明",
}

# 重量換算にJIS規格表が必要（断面が一定でないため体積式が使えない）
_JIS_NEEDS_MASTER = (C.H_BEAM, C.CHANNEL, C.ANGLE)

# usability 区分
U_READY = "ready"
U_REVIEW = "usable_with_review"
U_NOT_BASE = "not_for_base_material"
U_NEEDS_JIS = "needs_jis_master"
U_INSUFFICIENT = "insufficient_data"

# plate 細分類（R6.1で再設計）
PLATE_RAW = "raw_plate"                       # 生板・定尺板・鋼板として明確
PLATE_RECT = "rectangular_cut_plate"          # 切板など矩形寸法が明確
PLATE_SHAPED = "shaped_cut_plate"             # 型切など外接寸法はあるが実形状は異形
PLATE_BENT = "bent_plate"                     # L曲げ/3方曲げ等の曲げ加工を含む
PLATE_PROCESSING = "plate_processing_only"    # 加工費のみで板寸法・板厚が不明
PLATE_UNKNOWN = "unknown_plate"               # 判定不能

_BENT_KW = ("曲げ", "R曲げ", "L曲げ", "3方曲げ", "ヘミング")
_SHAPED_KW = ("型切", "異形", "窓枠", "枠", "レーザー", "孔", "穴", "切欠", "抜き")
_RECT_KW = ("切板", "シャーリング", "切断", "ガス切")
_RAW_KW = ("定尺", "板取", "生板", "鋼板", "鉄板", "縞鋼板", "プレート", "PL")

# 材質別密度 g/cm3。(密度, is_assumed, note) を返す。
_DENSITY = {
    "SS400": 7.85, "SM490": 7.85, "SPHC": 7.85, "SPCC": 7.85,
    "S45C": 7.85, "S50C": 7.85, "SGP": 7.85,
    "SUS304": 7.93, "SUS316": 7.98, "SUS316L": 7.98, "SUS430": 7.70,
}


def density_for_grade(grade: str):
    """材質グレード→(密度 g/cm3, is_assumed, note)。

    SS400=7.85 / SUS304=7.93。アルミ(A####/AL)は7.85では3倍過大評価になるため
    2.70で計算（is_assumed=Falseだがnoteで明示）。不明は7.85を仮定しwarningに残す。
    """
    g = (grade or "").upper().replace(" ", "")
    if g in _DENSITY:
        return _DENSITY[g], False, ""
    if g.startswith("SUS"):
        return 7.93, False, "SUS仮定密度7.93"
    if g in ("AL", "アルミ") or (g.startswith("A") and any(c.isdigit() for c in g)):
        return 2.70, False, "アルミ材: 密度2.70で計算"
    if not g:
        return 7.85, True, "材質不明: 鉄密度7.85を仮定"
    return 7.85, True, f"材質{grade}: 鉄密度7.85を仮定"


# ============================================================
# 出力フィールド定義
# ============================================================

# 注: 既存の latest_unit_price / median_unit_price / average_unit_price /
#     price_per_m / price_per_kg は「税抜(ex_tax)」。*_inc_tax が税込標準値。
PRACTICAL_MASTER_FIELDS = (
    "vendor_name", "material_category", "material_grade", "display_name",
    "normalized_spec", "spec_key", "candidate_class", "latest_unit_price",
    "price_unit", "price_per_m", "price_per_kg", "stock_length_mm",
    "estimated_weight_kg_per_stock", "median_unit_price", "average_unit_price",
    "sample_count", "latest_quote_date", "confidence", "usability",
    "usable_as_base_price", "usable_as_reference",
    # 税抜の単価レンジ（R6.3）
    "min_unit_price", "max_unit_price",
    # --- 消費税（R6.2） ---
    "tax_rate",
    "latest_unit_price_ex_tax", "latest_unit_price_tax", "latest_unit_price_inc_tax",
    "median_unit_price_ex_tax", "median_unit_price_tax", "median_unit_price_inc_tax",
    "average_unit_price_ex_tax", "average_unit_price_tax", "average_unit_price_inc_tax",
    "price_per_m_ex_tax", "price_per_m_tax", "price_per_m_inc_tax",
    "price_per_kg_ex_tax", "price_per_kg_tax", "price_per_kg_inc_tax",
    "warning", "notes",
)

# 注: unit_price / amount / price_per_m2 / price_per_kg は「税抜」。*_inc_tax が税込。
PLATE_REFERENCE_FIELDS = (
    "item_name", "material_grade", "plate_class", "thickness_mm", "width_mm",
    "height_mm", "quantity", "unit_price", "amount", "estimated_area_m2_each",
    "estimated_area_m2_total", "estimated_weight_kg_each", "estimated_weight_kg_total",
    "price_per_m2", "price_per_kg", "quote_date", "source_pdf", "source_page",
    "usable_as_reference", "usable_as_base_price", "confidence",
    # --- 消費税（R6.2） ---
    "tax_rate",
    "unit_price_ex_tax", "unit_price_tax", "unit_price_inc_tax",
    "amount_ex_tax", "amount_tax", "amount_inc_tax",
    "price_per_m2_ex_tax", "price_per_m2_tax", "price_per_m2_inc_tax",
    "price_per_kg_ex_tax", "price_per_kg_tax", "price_per_kg_inc_tax",
    "warning", "notes",
)

PLATE_SUMMARY_FIELDS = (
    "material_grade", "thickness_mm", "plate_class", "sample_count",
    "latest_quote_date", "latest_price_per_kg", "median_price_per_kg",
    "average_price_per_kg", "min_price_per_kg", "max_price_per_kg",
    "latest_price_per_m2", "median_price_per_m2", "average_price_per_m2",
    "min_price_per_m2", "max_price_per_m2", "usable_as_reference",
    "confidence",
    # --- 消費税（R6.2） ---
    "tax_rate",
    "latest_price_per_kg_ex_tax", "latest_price_per_kg_tax", "latest_price_per_kg_inc_tax",
    "median_price_per_kg_ex_tax", "median_price_per_kg_tax", "median_price_per_kg_inc_tax",
    "average_price_per_kg_ex_tax", "average_price_per_kg_tax", "average_price_per_kg_inc_tax",
    "latest_price_per_m2_ex_tax", "latest_price_per_m2_tax", "latest_price_per_m2_inc_tax",
    "median_price_per_m2_ex_tax", "median_price_per_m2_tax", "median_price_per_m2_inc_tax",
    "warning", "notes",
)

# plate_reference を mapping/master に出すときの必須warning
PLATE_REF_WARNING = "型切/切板由来の外接矩形ベース参考単価。生板単価ではないため要確認。"


# ============================================================
# 換算ヘルパー
# ============================================================

def _f(v):
    return cu.to_float(v)


def _g(v):
    """数値を簡潔表記、Noneは空文字。"""
    if v is None or v == "":
        return ""
    try:
        return f"{float(v):g}"
    except (TypeError, ValueError):
        return str(v)


def _round_g(v, ndigits=1):
    if v is None:
        return ""
    return f"{round(float(v), ndigits):g}"


def stock_weight_kg(cat: str, parsed: dict) -> float | None:
    """spec_key由来の寸法から定尺1本の重量(kg)を推定。換算不能なら None。

    アングル・チャンネル・H形鋼は断面が一定でないため None（JIS表が必要）。
    """
    if cat in _JIS_NEEDS_MASTER:
        return None
    req = MaterialRequest(
        material_category=cat,
        diameter_mm=parsed.get("diameter"),
        thickness_mm=parsed.get("thickness"),
        width_mm=parsed.get("width"),
        height_mm=parsed.get("height"),
        length_mm=parsed.get("length"),
    )
    return est.estimate_weight_kg(req)


# これ未満の長さは定尺ではなく切断材（端材）の可能性が高く、m単価換算が無意味
_MIN_STOCK_LENGTH_MM = 1000.0


def conversions(cat: str, parsed: dict, latest_price: float | None) -> dict:
    """price_per_m / price_per_kg / stock_length / weight を計算する。

    全レコードが price_unit='個'（＝定尺1本単価）である前提で、
    spec_key の L トークンを定尺長として m単価へ、重量式で kg単価へ換算する。
    ただし L が短い（<1m）ものは切断材とみなし m単価を出さない（誤誘導防止）。
    """
    length = parsed.get("length")
    weight = stock_weight_kg(cat, parsed)
    short_piece = length is not None and length < _MIN_STOCK_LENGTH_MM
    price_per_m = None
    price_per_kg = None
    if latest_price is not None and length and length > 0 and not short_piece:
        price_per_m = latest_price / (length / 1000.0)
    if latest_price is not None and weight and weight > 0:
        price_per_kg = latest_price / weight
    return {
        "stock_length_mm": length,
        "estimated_weight_kg_per_stock": weight,
        "price_per_m": price_per_m,
        "price_per_kg": price_per_kg,
        "short_piece": short_piece,
    }


def _display_name(cat: str, grade: str, parsed: dict) -> str:
    label = JP_LABEL.get(cat, cat)
    bits = []
    if parsed.get("diameter") is not None:
        bits.append(f"φ{_g(parsed['diameter'])}")
    if parsed.get("width") is not None and parsed.get("height") is not None:
        bits.append(f"{_g(parsed['width'])}x{_g(parsed['height'])}")
    elif parsed.get("width") is not None:
        bits.append(f"W{_g(parsed['width'])}")
    if parsed.get("thickness") is not None:
        bits.append(f"t{_g(parsed['thickness'])}")
    if parsed.get("length") is not None:
        bits.append(f"L{_g(parsed['length'])}")
    spec = " ".join(bits)
    return f"{label} {grade} {spec}".replace("  ", " ").strip()


# ============================================================
# usability 判定
# ============================================================

def decide_usability(cclass: str, cat: str, sample_count: int,
                     has_m: bool, has_kg: bool, needs_review: bool) -> str:
    if cclass == cp.CLASS_PROCESSED:
        return U_NOT_BASE
    if cat in (C.H_BEAM, C.CHANNEL):
        return U_NEEDS_JIS
    if cclass == cp.CLASS_PLATE or cat == C.PLATE:
        # 板材は生材単価として自動採用しない（参考表で別途扱う）
        return U_NOT_BASE
    if not (has_m or has_kg):
        # 換算もできずサンプルも薄い → データ不足
        return U_INSUFFICIENT if sample_count < 2 else U_REVIEW
    if sample_count >= 2 and not needs_review:
        return U_READY
    return U_REVIEW


# ============================================================
# 実用単価マスター（practical price master）
# ============================================================

def _master_row_for_plate_reference(p: dict, rate: float = tx.DEFAULT_TAX_RATE) -> dict:
    """板厚別参考単価(plate_reference_summary)1行 → practical_master行。"""
    grade = p.get("material_grade", "")
    thick = p.get("thickness_mm", "")
    pclass = p.get("plate_class", "")
    kg = p.get("median_price_per_kg", "")
    row = {
        "vendor_name": "東鋼材",
        "material_category": C.PLATE,
        "material_grade": grade,
        "display_name": f"鋼板(型切参考) {grade} t{thick} [{pclass}]".strip(),
        "normalized_spec": f"{grade}_PL_t{thick}".strip("_"),
        "spec_key": f"plate_ref|{grade}|t{thick}|{pclass}",
        "candidate_class": "plate_reference",
        "latest_unit_price": "",
        "price_unit": "kg",
        "price_per_m": "",
        "price_per_kg": kg,
        "stock_length_mm": "",
        "estimated_weight_kg_per_stock": "",
        "median_unit_price": "",
        "average_unit_price": "",
        "sample_count": p.get("sample_count", ""),
        "latest_quote_date": p.get("latest_quote_date", ""),
        "confidence": p.get("confidence", 0.4),
        "usability": U_REVIEW,
        "usable_as_base_price": "false",
        "usable_as_reference": "true",
        "tax_rate": tx.normalize_rate(rate),
        "warning": p.get("warning", PLATE_REF_WARNING),
        "notes": "型切/切板由来。外接矩形ベース。price_per_kgは税抜。",
    }
    row.update(tx.tax_columns("price_per_kg", kg, rate))
    return row


def build_practical_master(summary_rows: list[dict],
                           plate_ref_summary: list[dict] | None = None,
                           tax_rate: float = tx.DEFAULT_TAX_RATE) -> list[dict]:
    """spec_key別サマリを「実務で選びやすい単価表」に変換する。

    加工品は削除せず not_for_base_material として残す。
    plate_ref_summary を渡すと、板厚別の参考単価を candidate_class=plate_reference
    として追加する（usable_as_base_price=false / usable_as_reference=true）。
    既存の単価列は税抜、*_inc_tax が税込標準値。
    """
    rate = tx.normalize_rate(tax_rate)
    out = []
    for s in summary_rows:
        cat = s.get("material_category", "") or ""
        grade = s.get("material_grade", "") or ""
        spec_key = s.get("spec_key", "") or ""
        parsed = cp.parse_spec_key(spec_key)
        latest = _f(s.get("latest_unit_price"))
        conv = conversions(cat, parsed, latest)
        sample = cu.to_int(s.get("sample_count")) or 0
        needs_review = str(s.get("needs_review", "")).strip() == "true"
        cclass = s.get("candidate_class", "") or ""
        has_m = conv["price_per_m"] is not None
        has_kg = conv["price_per_kg"] is not None
        usability = decide_usability(cclass, cat, sample, has_m, has_kg, needs_review)

        warn = []
        if s.get("warning"):
            warn.append(s["warning"])
        if cat in _JIS_NEEDS_MASTER and not has_kg:
            warn.append("重量換算にはJIS規格表が必要(price_per_kg未算出)")
        if conv.get("short_piece"):
            warn.append("短尺(<1m)のため切断材の可能性: m単価は参考外")
            # 切断材は定尺生材として確定させない
            if usability == U_READY:
                usability = U_REVIEW
        elif not has_m and usability not in (U_NOT_BASE, U_NEEDS_JIS):
            warn.append("定尺長(L)不明のためm単価未算出")

        latest_s = _g(latest)
        median_s = _g(_f(s.get("median_unit_price")))
        average_s = _g(_f(s.get("average_unit_price")))
        ppm_s = _round_g(conv["price_per_m"], 1)
        ppk_s = _round_g(conv["price_per_kg"], 1)
        row = {
            "vendor_name": s.get("vendor_name", ""),
            "material_category": cat,
            "material_grade": grade,
            "display_name": _display_name(cat, grade, parsed),
            "normalized_spec": s.get("normalized_spec", ""),
            "spec_key": spec_key,
            "candidate_class": cclass,
            "latest_unit_price": latest_s,
            "price_unit": s.get("price_unit", "個") or "個",
            "price_per_m": ppm_s,
            "price_per_kg": ppk_s,
            "stock_length_mm": _g(conv["stock_length_mm"]),
            "estimated_weight_kg_per_stock": _round_g(conv["estimated_weight_kg_per_stock"], 2),
            "median_unit_price": median_s,
            "average_unit_price": average_s,
            "sample_count": sample,
            "latest_quote_date": s.get("latest_quote_date", ""),
            "confidence": s.get("confidence", ""),
            "usability": usability,
            "usable_as_base_price": "true" if usability in (U_READY, U_REVIEW) else "false",
            "usable_as_reference": "true" if (has_m or has_kg) else "false",
            "min_unit_price": _g(_f(s.get("min_unit_price"))),
            "max_unit_price": _g(_f(s.get("max_unit_price"))),
            "tax_rate": rate,
            "warning": "; ".join(warn),
            "notes": "自動算出の参考値。最終確定は人間が行う。既存単価列は税抜。",
        }
        row.update(tx.tax_columns("latest_unit_price", latest_s, rate))
        row.update(tx.tax_columns("median_unit_price", median_s, rate))
        row.update(tx.tax_columns("average_unit_price", average_s, rate))
        row.update(tx.tax_columns("price_per_m", ppm_s, rate))
        row.update(tx.tax_columns("price_per_kg", ppk_s, rate))
        out.append(row)
    out.sort(key=lambda r: (r["material_category"], r["spec_key"]))
    if plate_ref_summary:
        out.extend(_master_row_for_plate_reference(p, rate) for p in plate_ref_summary)
    return out


def write_practical_master(path: str, rows: list[dict]) -> int:
    return cu.write_dicts(path, PRACTICAL_MASTER_FIELDS, rows)


# ============================================================
# 板材（plate）の再分析
# ============================================================

def classify_plate(text: str, has_thickness: bool = True, has_wh: bool = True) -> str:
    """板材を raw/rectangular_cut/shaped_cut/bent/processing_only/unknown に分類する。

    型切は原則 shaped_cut_plate（外接寸法はあるが実形状は異形）。
    寸法・板厚が取れない加工キーワード行は plate_processing_only。
    """
    t = text or ""
    has_dims = has_thickness and has_wh
    if any(k in t for k in _BENT_KW):
        return PLATE_BENT if has_dims else PLATE_PROCESSING
    if any(k in t for k in _SHAPED_KW):
        return PLATE_SHAPED if has_dims else PLATE_PROCESSING
    if any(k in t for k in _RECT_KW):
        return PLATE_RECT if has_dims else PLATE_PROCESSING
    if any(k in t for k in _RAW_KW):
        return PLATE_RAW
    return PLATE_UNKNOWN


def build_plate_reference(candidate_rows: list[dict],
                          tax_rate: float = tx.DEFAULT_TAX_RATE) -> list[dict]:
    """plate候補から外接矩形ベースの参考価格表を作る。

    型切・切板は生材単価(usable_as_base_price)としては使わないが、板厚・外接寸法・
    数量・金額が取れるものは usable_as_reference=true として参考kg/㎡単価を計算する。
    重量・単価は原則 amount（=単価×数量）と total を用いる。単価列は税抜。
    """
    rate = tx.normalize_rate(tax_rate)
    out = []
    for r in candidate_rows:
        if r.get("material_category") != C.PLATE:
            continue
        grade = r.get("material_grade", "") or ""
        text = " ".join(str(r.get(k, "") or "") for k in ("spec_text", "notes"))
        parsed = cp.parse_spec_key(r.get("spec_key", ""))
        t = parsed.get("thickness")
        w = parsed.get("width")
        h = parsed.get("height")
        qty = _f(r.get("quantity")) or 1.0
        unit_price = _f(r.get("unit_price"))
        amount = _f(r.get("amount"))
        # 金額が無ければ 単価×数量 で補完（単価だけで判断しない）
        total_price = amount if amount is not None else (
            unit_price * qty if unit_price is not None else None)

        density, assumed, dnote = density_for_grade(grade)
        has_wh = bool(w and h)
        has_t = t is not None
        plate_class = classify_plate(text, has_t, has_wh)

        area_each = (w / 1000.0) * (h / 1000.0) if has_wh else None
        area_total = area_each * qty if area_each is not None else None
        weight_each = area_each * t * density if (area_each is not None and has_t) else None
        weight_total = weight_each * qty if weight_each is not None else None
        price_per_m2 = (total_price / area_total
                        if area_total and total_price is not None else None)
        price_per_kg = (total_price / weight_total
                        if weight_total and total_price is not None else None)

        # 鋼材/SUS/アルミの実勢kg単価は概ね150〜2000円/kg。これを大きく超える/0以下は
        # 微小部品の最低チャージ効果やデータ不良であり、素材参考単価として誤誘導する。
        implausible = price_per_kg is not None and (price_per_kg <= 0 or price_per_kg > 5000)
        usable_ref = (plate_class != PLATE_PROCESSING and price_per_kg is not None
                      and price_per_kg > 0 and not implausible and has_t and has_wh)
        warn = [PLATE_REF_WARNING]
        if plate_class in (PLATE_SHAPED, PLATE_BENT):
            warn.append("外接矩形のため実重量を過大評価しうる（kg単価は割安に出る）")
        if implausible:
            warn.append("kg単価が妥当域外(>5000 or ≤0): 微小部品の最低チャージ等。参考外")
        if dnote:
            warn.append(dnote)
        if assumed:
            warn.append("密度仮定により重量不確実")
        if not (has_t and has_wh):
            warn.append("板厚または外接寸法が不足")

        # confidence: 生板でなく型切由来なので低め。データ完全性で微調整。
        conf = 0.5 if plate_class == PLATE_RAW else 0.4
        if not usable_ref:
            conf = 0.2

        up_s = _g(unit_price)
        amt_s = _g(amount)
        m2_s = _round_g(price_per_m2, 0)
        kg_s = _round_g(price_per_kg, 1)
        prow = {
            "item_name": r.get("spec_text", "") or text.strip(),
            "material_grade": grade,
            "plate_class": plate_class,
            "thickness_mm": _g(t),
            "width_mm": _g(w),
            "height_mm": _g(h),
            "quantity": _g(qty),
            "unit_price": up_s,
            "amount": amt_s,
            "estimated_area_m2_each": _round_g(area_each, 4),
            "estimated_area_m2_total": _round_g(area_total, 4),
            "estimated_weight_kg_each": _round_g(weight_each, 2),
            "estimated_weight_kg_total": _round_g(weight_total, 2),
            "price_per_m2": m2_s,
            "price_per_kg": kg_s,
            "quote_date": r.get("quote_date", ""),
            "source_pdf": r.get("source_pdf", ""),
            "source_page": r.get("source_page", ""),
            "usable_as_reference": "true" if usable_ref else "false",
            "usable_as_base_price": "false",
            "confidence": conf,
            "tax_rate": rate,
            "warning": "; ".join(warn),
            "notes": "型切/切板由来。外接矩形ベース。生材単価として自動採用しない。単価列は税抜。",
        }
        prow.update(tx.tax_columns("unit_price", up_s, rate))
        prow.update(tx.tax_columns("amount", amt_s, rate))
        prow.update(tx.tax_columns("price_per_m2", m2_s, rate))
        prow.update(tx.tax_columns("price_per_kg", kg_s, rate))
        out.append(prow)
    out.sort(key=lambda r: (_f(r["thickness_mm"]) or 0, r["material_grade"], r["item_name"]))
    return out


def write_plate_reference(path: str, rows: list[dict]) -> int:
    return cu.write_dicts(path, PLATE_REFERENCE_FIELDS, rows)


def build_plate_reference_summary(plate_ref_rows: list[dict],
                                  tax_rate: float = tx.DEFAULT_TAX_RATE) -> list[dict]:
    """参考価格行を 材質×板厚×plate_class で集約し、板厚別参考単価表を作る。単価列は税抜。"""
    rate = tx.normalize_rate(tax_rate)
    groups: dict[tuple, list[dict]] = {}
    for r in plate_ref_rows:
        if r.get("usable_as_reference") != "true":
            continue
        key = (r.get("material_grade", ""), r.get("thickness_mm", ""), r.get("plate_class", ""))
        groups.setdefault(key, []).append(r)

    out = []
    for (grade, thick, pclass), members in groups.items():
        kgs = [_f(m.get("price_per_kg")) for m in members]
        kgs = [v for v in kgs if v is not None]
        m2s = [_f(m.get("price_per_m2")) for m in members]
        m2s = [v for v in m2s if v is not None]
        latest = max(members, key=lambda m: m.get("quote_date") or "")
        if not kgs:
            continue
        latest_kg = latest.get("price_per_kg", "")
        median_kg = _round_g(statistics.median(kgs), 1)
        avg_kg = _round_g(statistics.fmean(kgs), 1)
        latest_m2 = latest.get("price_per_m2", "")
        median_m2 = _round_g(statistics.median(m2s), 0) if m2s else ""
        row = {
            "material_grade": grade,
            "thickness_mm": thick,
            "plate_class": pclass,
            "sample_count": len(members),
            "latest_quote_date": latest.get("quote_date", ""),
            "latest_price_per_kg": latest_kg,
            "median_price_per_kg": median_kg,
            "average_price_per_kg": avg_kg,
            "min_price_per_kg": _round_g(min(kgs), 1),
            "max_price_per_kg": _round_g(max(kgs), 1),
            "latest_price_per_m2": latest_m2,
            "median_price_per_m2": median_m2,
            "average_price_per_m2": _round_g(statistics.fmean(m2s), 0) if m2s else "",
            "min_price_per_m2": _round_g(min(m2s), 0) if m2s else "",
            "max_price_per_m2": _round_g(max(m2s), 0) if m2s else "",
            "usable_as_reference": "true",
            "confidence": 0.5 if pclass == PLATE_RAW else 0.4,
            "tax_rate": rate,
            "warning": PLATE_REF_WARNING,
            "notes": "型切/切板由来。外接矩形ベース。板厚別の参考単価。単価列は税抜。",
        }
        row.update(tx.tax_columns("latest_price_per_kg", latest_kg, rate))
        row.update(tx.tax_columns("median_price_per_kg", median_kg, rate))
        row.update(tx.tax_columns("average_price_per_kg", avg_kg, rate))
        row.update(tx.tax_columns("latest_price_per_m2", latest_m2, rate))
        row.update(tx.tax_columns("median_price_per_m2", median_m2, rate))
        out.append(row)
    out.sort(key=lambda r: (_f(r["thickness_mm"]) or 0, r["material_grade"], r["plate_class"]))
    return out


def write_plate_reference_summary(path: str, rows: list[dict]) -> int:
    return cu.write_dicts(path, PLATE_SUMMARY_FIELDS, rows)


# ============================================================
# 分析テーブル群（tables-out/ に出力する個別CSV）
# ============================================================

def _stats(prices: list[float]) -> dict:
    clean = [p for p in prices if p is not None]
    if not clean:
        return {"n": 0, "median": None, "mean": None, "min": None, "max": None}
    return {
        "n": len(clean),
        "median": statistics.median(clean),
        "mean": statistics.fmean(clean),
        "min": min(clean),
        "max": max(clean),
    }


def _category_overview(cand: list[dict]) -> list[dict]:
    cats: dict[str, list[dict]] = {}
    for r in cand:
        cats.setdefault(r.get("material_category", ""), []).append(r)
    rows = []
    for cat, members in cats.items():
        by_class: dict[str, int] = {}
        for m in members:
            by_class[m["candidate_class"]] = by_class.get(m["candidate_class"], 0) + 1
        prices = [_f(m.get("unit_price")) for m in members]
        st = _stats(prices)
        rows.append({
            "material_category": cat,
            "label": JP_LABEL.get(cat, cat),
            "total_count": len(members),
            "base_material": by_class.get(cp.CLASS_BASE, 0),
            "plate_material": by_class.get(cp.CLASS_PLATE, 0),
            "processed_item": by_class.get(cp.CLASS_PROCESSED, 0),
            "jis_shape_needs_master": by_class.get(cp.CLASS_JIS, 0),
            "unknown": by_class.get(cp.CLASS_UNKNOWN, 0),
            "with_price": st["n"],
            "median_unit_price": _round_g(st["median"], 0),
            "min_unit_price": _g(st["min"]),
            "max_unit_price": _g(st["max"]),
        })
    rows.sort(key=lambda r: -r["total_count"])
    return rows


def _class_overview(cand: list[dict], cclass: str) -> list[dict]:
    """指定 candidate_class のカテゴリ別概観。"""
    sub = [r for r in cand if r["candidate_class"] == cclass]
    cats: dict[str, list[dict]] = {}
    for r in sub:
        cats.setdefault(r.get("material_category", ""), []).append(r)
    rows = []
    for cat, members in cats.items():
        prices = [_f(m.get("unit_price")) for m in members]
        st = _stats(prices)
        rows.append({
            "material_category": cat,
            "label": JP_LABEL.get(cat, cat),
            "count": len(members),
            "with_price": st["n"],
            "median_unit_price": _round_g(st["median"], 0),
            "min_unit_price": _g(st["min"]),
            "max_unit_price": _g(st["max"]),
        })
    rows.sort(key=lambda r: -r["count"])
    return rows


def _price_range_by_category(summary: list[dict]) -> list[dict]:
    cats: dict[str, list[dict]] = {}
    for s in summary:
        cats.setdefault(s.get("material_category", ""), []).append(s)
    rows = []
    for cat, members in cats.items():
        prices = [_f(m.get("latest_unit_price")) for m in members]
        st = _stats(prices)
        rows.append({
            "material_category": cat,
            "label": JP_LABEL.get(cat, cat),
            "spec_key_count": len(members),
            "min_unit_price": _g(st["min"]),
            "median_unit_price": _round_g(st["median"], 0),
            "max_unit_price": _g(st["max"]),
            "range_ratio": _round_g((st["max"] / st["min"]) if st["min"] else None, 1),
        })
    rows.sort(key=lambda r: -r["spec_key_count"])
    return rows


def _latest_prices_by_category(summary: list[dict], top=5) -> list[dict]:
    cats: dict[str, list[dict]] = {}
    for s in summary:
        cats.setdefault(s.get("material_category", ""), []).append(s)
    rows = []
    for cat, members in cats.items():
        members_sorted = sorted(members, key=lambda m: m.get("latest_quote_date") or "", reverse=True)
        for m in members_sorted[:top]:
            rows.append({
                "material_category": cat,
                "normalized_spec": m.get("normalized_spec", ""),
                "spec_key": m.get("spec_key", ""),
                "latest_unit_price": m.get("latest_unit_price", ""),
                "latest_quote_date": m.get("latest_quote_date", ""),
                "sample_count": m.get("sample_count", ""),
            })
    return rows


def _unit_conversion_candidates(master: list[dict]) -> list[dict]:
    rows = []
    for m in master:
        if m["usability"] == U_NOT_BASE:
            continue  # 板材・加工品は生材換算表に載せない
        if m["price_per_m"] or m["price_per_kg"]:
            rows.append({
                "material_category": m["material_category"],
                "display_name": m["display_name"],
                "spec_key": m["spec_key"],
                "latest_unit_price": m["latest_unit_price"],
                "stock_length_mm": m["stock_length_mm"],
                "price_per_m": m["price_per_m"],
                "estimated_weight_kg_per_stock": m["estimated_weight_kg_per_stock"],
                "price_per_kg": m["price_per_kg"],
                "usability": m["usability"],
            })
    return rows


def _low_confidence_items(summary: list[dict]) -> list[dict]:
    rows = []
    for s in summary:
        conf = _f(s.get("confidence"))
        sample = cu.to_int(s.get("sample_count")) or 0
        if (conf is not None and conf < 0.5) or sample < 2 or s.get("needs_review") == "true":
            rows.append({
                "material_category": s.get("material_category", ""),
                "normalized_spec": s.get("normalized_spec", ""),
                "spec_key": s.get("spec_key", ""),
                "candidate_class": s.get("candidate_class", ""),
                "confidence": s.get("confidence", ""),
                "sample_count": sample,
                "needs_review": s.get("needs_review", ""),
                "warning": s.get("warning", ""),
            })
    return rows


def _outlier_items(summary: list[dict]) -> list[dict]:
    rows = []
    for s in summary:
        if s.get("warning"):
            rows.append({
                "material_category": s.get("material_category", ""),
                "normalized_spec": s.get("normalized_spec", ""),
                "spec_key": s.get("spec_key", ""),
                "latest_unit_price": s.get("latest_unit_price", ""),
                "median_unit_price": s.get("median_unit_price", ""),
                "min_unit_price": s.get("min_unit_price", ""),
                "max_unit_price": s.get("max_unit_price", ""),
                "sample_count": s.get("sample_count", ""),
                "warning": s.get("warning", ""),
            })
    return rows


def _category_detail(master: list[dict], cat: str) -> list[dict]:
    """カテゴリ別の代表単価表（practical master の抜粋）。"""
    rows = []
    for m in master:
        if m["material_category"] != cat:
            continue
        rows.append({
            "display_name": m["display_name"],
            "material_grade": m["material_grade"],
            "spec_key": m["spec_key"],
            "latest_unit_price": m["latest_unit_price"],
            "price_per_m": m["price_per_m"],
            "price_per_kg": m["price_per_kg"],
            "stock_length_mm": m["stock_length_mm"],
            "median_unit_price": m["median_unit_price"],
            "sample_count": m["sample_count"],
            "latest_quote_date": m["latest_quote_date"],
            "usability": m["usability"],
        })
    rows.sort(key=lambda r: r["spec_key"])
    return rows


def _plate_items_analysis(plate_ref: list[dict]) -> list[dict]:
    by_class: dict[str, list[dict]] = {}
    for r in plate_ref:
        by_class.setdefault(r["plate_class"], []).append(r)
    rows = []
    for pclass, members in by_class.items():
        kgs = [_f(m.get("price_per_kg")) for m in members]
        st = _stats(kgs)
        rows.append({
            "plate_class": pclass,
            "count": len(members),
            "with_price_per_kg": st["n"],
            "median_price_per_kg": _round_g(st["median"], 1),
            "min_price_per_kg": _round_g(st["min"], 1),
            "max_price_per_kg": _round_g(st["max"], 1),
            "usable_as_reference": sum(1 for m in members if m["usable_as_reference"] == "true"),
        })
    rows.sort(key=lambda r: -r["count"])
    return rows


def _unmapped_reason_analysis(summary: list[dict]) -> list[dict]:
    """カテゴリ別に「Rhinoレイヤー提案に使えない理由」を集計する。"""
    cats: dict[str, dict] = {}
    for s in summary:
        cat = s.get("material_category", "")
        d = cats.setdefault(cat, {"total": 0, "usable": 0, "processed": 0,
                                  "jis": 0, "missing_dims": 0, "low_sample": 0})
        d["total"] += 1
        cclass = s.get("candidate_class", "")
        if s.get("usable_as_base_price") == "true":
            d["usable"] += 1
        if cclass == cp.CLASS_PROCESSED:
            d["processed"] += 1
        if cclass == cp.CLASS_JIS or cat in (C.H_BEAM, C.CHANNEL):
            d["jis"] += 1
        parsed = cp.parse_spec_key(s.get("spec_key", ""))
        if parsed.get("length") is None:
            d["missing_dims"] += 1
        if (cu.to_int(s.get("sample_count")) or 0) < 2:
            d["low_sample"] += 1
    rows = []
    for cat, d in cats.items():
        reasons = []
        if d["processed"]:
            reasons.append(f"加工品{d['processed']}件")
        if d["jis"]:
            reasons.append(f"JIS要マスター{d['jis']}件")
        if d["missing_dims"]:
            reasons.append(f"定尺長欠落{d['missing_dims']}件")
        if d["low_sample"]:
            reasons.append(f"サンプル<2:{d['low_sample']}件")
        rows.append({
            "material_category": cat,
            "label": JP_LABEL.get(cat, cat),
            "total_spec_keys": d["total"],
            "usable_base": d["usable"],
            "processed": d["processed"],
            "jis_needs_master": d["jis"],
            "length_missing": d["missing_dims"],
            "low_sample": d["low_sample"],
            "main_reason_no_mapping": "; ".join(reasons) or "なし",
        })
    rows.sort(key=lambda r: -r["total_spec_keys"])
    return rows


TABLE_FIELDS = {
    "category_overview": ("material_category", "label", "total_count", "base_material",
                          "plate_material", "processed_item", "jis_shape_needs_master",
                          "unknown", "with_price", "median_unit_price",
                          "min_unit_price", "max_unit_price"),
    "base_material_overview": ("material_category", "label", "count", "with_price",
                               "median_unit_price", "min_unit_price", "max_unit_price"),
    "processed_item_overview": ("material_category", "label", "count", "with_price",
                                "median_unit_price", "min_unit_price", "max_unit_price"),
    "price_range_by_category": ("material_category", "label", "spec_key_count",
                                "min_unit_price", "median_unit_price", "max_unit_price",
                                "range_ratio"),
    "latest_prices_by_category": ("material_category", "normalized_spec", "spec_key",
                                  "latest_unit_price", "latest_quote_date", "sample_count"),
    "unit_conversion_candidates": ("material_category", "display_name", "spec_key",
                                   "latest_unit_price", "stock_length_mm", "price_per_m",
                                   "estimated_weight_kg_per_stock", "price_per_kg", "usability"),
    "low_confidence_items": ("material_category", "normalized_spec", "spec_key",
                             "candidate_class", "confidence", "sample_count",
                             "needs_review", "warning"),
    "outlier_items": ("material_category", "normalized_spec", "spec_key",
                      "latest_unit_price", "median_unit_price", "min_unit_price",
                      "max_unit_price", "sample_count", "warning"),
    "plate_items_analysis": ("plate_class", "count", "with_price_per_kg",
                             "median_price_per_kg", "min_price_per_kg",
                             "max_price_per_kg", "usable_as_reference"),
    "pipe_items_analysis": ("display_name", "material_grade", "spec_key", "latest_unit_price",
                            "price_per_m", "price_per_kg", "stock_length_mm",
                            "median_unit_price", "sample_count", "latest_quote_date", "usability"),
    "square_pipe_items_analysis": ("display_name", "material_grade", "spec_key", "latest_unit_price",
                                   "price_per_m", "price_per_kg", "stock_length_mm",
                                   "median_unit_price", "sample_count", "latest_quote_date", "usability"),
    "angle_items_analysis": ("display_name", "material_grade", "spec_key", "latest_unit_price",
                             "price_per_m", "price_per_kg", "stock_length_mm",
                             "median_unit_price", "sample_count", "latest_quote_date", "usability"),
    "flat_bar_items_analysis": ("display_name", "material_grade", "spec_key", "latest_unit_price",
                                "price_per_m", "price_per_kg", "stock_length_mm",
                                "median_unit_price", "sample_count", "latest_quote_date", "usability"),
    "round_bar_items_analysis": ("display_name", "material_grade", "spec_key", "latest_unit_price",
                                 "price_per_m", "price_per_kg", "stock_length_mm",
                                 "median_unit_price", "sample_count", "latest_quote_date", "usability"),
    "unmapped_reason_analysis": ("material_category", "label", "total_spec_keys", "usable_base",
                                 "processed", "jis_needs_master", "length_missing",
                                 "low_sample", "main_reason_no_mapping"),
}


def build_tables(cand: list[dict], summary: list[dict], master: list[dict],
                 plate_ref: list[dict]) -> dict[str, list[dict]]:
    """tables-out/ に出す全テーブルを dict[name -> rows] で返す。"""
    return {
        "category_overview": _category_overview(cand),
        "base_material_overview": _class_overview(cand, cp.CLASS_BASE),
        "processed_item_overview": _class_overview(cand, cp.CLASS_PROCESSED),
        "price_range_by_category": _price_range_by_category(summary),
        "latest_prices_by_category": _latest_prices_by_category(summary),
        "unit_conversion_candidates": _unit_conversion_candidates(master),
        "low_confidence_items": _low_confidence_items(summary),
        "outlier_items": _outlier_items(summary),
        "plate_items_analysis": _plate_items_analysis(plate_ref),
        "pipe_items_analysis": _category_detail(master, C.ROUND_PIPE),
        "square_pipe_items_analysis": _category_detail(master, C.SQUARE_PIPE),
        "angle_items_analysis": _category_detail(master, C.ANGLE),
        "flat_bar_items_analysis": _category_detail(master, C.FLAT_BAR),
        "round_bar_items_analysis": _category_detail(master, C.ROUND_BAR),
        "unmapped_reason_analysis": _unmapped_reason_analysis(summary),
    }


def write_tables(out_dir: str, tables: dict[str, list[dict]]) -> list[str]:
    import os
    os.makedirs(out_dir, exist_ok=True)
    written = []
    for name, rows in tables.items():
        path = os.path.join(out_dir, f"{name}.csv")
        cu.write_dicts(path, TABLE_FIELDS[name], rows)
        written.append(path)
    return written


# ============================================================
# Markdown レポート
# ============================================================

def build_report(cand: list[dict], summary: list[dict], master: list[dict],
                 plate_ref: list[dict], tables: dict[str, list[dict]],
                 vendor: str, now_str: str = "",
                 plate_ref_summary: list[dict] | None = None,
                 tax_rate: float = tx.DEFAULT_TAX_RATE) -> str:
    rate = tx.normalize_rate(tax_rate)
    total = len(cand)
    by_class: dict[str, int] = {}
    for r in cand:
        by_class[r["candidate_class"]] = by_class.get(r["candidate_class"], 0) + 1
    needs_review = sum(1 for s in summary if s.get("needs_review") == "true")
    usable_master = [m for m in master if m["usability"] in (U_READY, U_REVIEW)]
    ready_master = [m for m in master if m["usability"] == U_READY]

    L = []
    A = L.append
    A("# 東鋼材 単価DB 分析レポート（Phase R6）")
    A("")
    A(f"- vendor: {vendor or '(全件)'}")
    if now_str:
        A(f"- 実行: {now_str}")
    A(f"- 総候補レコード数: {total}")
    A(f"- spec_key集約数: {len(summary)}")
    A(f"- needs_review(spec_key): {needs_review}")
    A(f"- practical_price_master件数: {len(master)} "
      f"(ready={len(ready_master)}, usable_with_review={len(usable_master)-len(ready_master)})")
    A("")
    A("## candidate_class 別件数")
    for k, label in ((cp.CLASS_BASE, "base_material"), (cp.CLASS_PLATE, "plate_material"),
                     (cp.CLASS_PROCESSED, "processed_item"),
                     (cp.CLASS_JIS, "jis_shape_needs_master"), (cp.CLASS_UNKNOWN, "unknown")):
        A(f"- {label}: {by_class.get(k, 0)}")
    A("")
    A("## カテゴリ別概観 (category_overview)")
    A("| カテゴリ | 件数 | 生材 | 加工 | with価格 | 中央値 | 最小 | 最大 |")
    A("|---|--:|--:|--:|--:|--:|--:|--:|")
    for r in tables["category_overview"]:
        A(f"| {r['label']} | {r['total_count']} | {r['base_material']} | "
          f"{r['processed_item']} | {r['with_price']} | {r['median_unit_price']} | "
          f"{r['min_unit_price']} | {r['max_unit_price']} |")
    A("")

    def cat_table(title, name, unit_col="price_per_m"):
        A(f"## {title}")
        rows = [r for r in tables[name] if r["usability"] in (U_READY, U_REVIEW)][:20]
        if not rows:
            rows = tables[name][:20]
        A("| 品名 | 規格 | 最新単価/本 | m単価 | kg単価 | 定尺mm | n | usability |")
        A("|---|---|--:|--:|--:|--:|--:|---|")
        for r in rows:
            A(f"| {r['display_name']} | {r['material_grade']} | {r['latest_unit_price']} | "
              f"{r['price_per_m']} | {r['price_per_kg']} | {r['stock_length_mm']} | "
              f"{r['sample_count']} | {r['usability']} |")
        A("")

    cat_table("丸パイプ 代表単価", "pipe_items_analysis")
    cat_table("角パイプ 代表単価", "square_pipe_items_analysis")
    cat_table("アングル 代表単価", "angle_items_analysis")
    cat_table("FB 代表単価", "flat_bar_items_analysis")
    cat_table("丸棒 代表単価", "round_bar_items_analysis")

    A("## 板材 参考kg単価 (plate_items_analysis)")
    A("| plate_class | 件数 | kg単価中央値 | 最小 | 最大 | 参考可 |")
    A("|---|--:|--:|--:|--:|--:|")
    for r in tables["plate_items_analysis"]:
        A(f"| {r['plate_class']} | {r['count']} | {r['median_price_per_kg']} | "
          f"{r['min_price_per_kg']} | {r['max_price_per_kg']} | {r['usable_as_reference']} |")
    A("")
    A("## 型切（shaped_cut_plate）の扱い")
    A("- **完全除外しない理由**: 東鋼材の「型切」は単なる加工費ではなく、SS400板の"
      "板厚・外接寸法・数量・単価・金額を持つ板材価格データである。除外すると板材の"
      "価格根拠が一切無くなり、Rhinoの鉄板レイヤーに候補を出せない。")
    A("- **生材単価として自動採用しない理由**: 型切は実形状が矩形ではなく、外接矩形面積で"
      "重量を計算するため実重量を過大評価しうる（kg単価は割安に出る）。さらにマーキング・"
      "穴あけ・小ロット加工費を含む可能性があり、生板の素材単価とは性質が異なる。")
    A("- **参考kg単価の計算方法**: price_per_kg = amount ÷ (外接面積×板厚×密度×数量)。"
      "amount(=単価×数量)とtotal重量を用いる。密度はSS400=7.85 / SUS304=7.93 / "
      "アルミ=2.70 / 不明=7.85(warning)。")
    A("- **限界**: ①実形状が矩形でない ②外接面積のため実重量を過大評価 "
      "③マーキング/穴/小ロット加工費を含む ④よってkg単価は参考値であり承認が必要。")
    A("- 結論: `usable_as_base_price=false` のまま `usable_as_reference=true` とし、"
      "raw_plateが無い板材見積の候補として warning 付きで提示する。")
    A("")
    if plate_ref_summary:
        A("## 板厚別 参考単価 (plate_reference_summary_by_thickness)")
        A("| 材質 | 板厚 | plate_class | n | kg単価中央 | kg最小 | kg最大 | ㎡単価中央 |")
        A("|---|--:|---|--:|--:|--:|--:|--:|")
        rep_grades = ("SS400",)
        prio = {PLATE_RAW: 0, PLATE_RECT: 1, PLATE_SHAPED: 2}
        shown = sorted(plate_ref_summary,
                       key=lambda r: (_f(r["thickness_mm"]) or 0, prio.get(r["plate_class"], 9)))
        for r in shown[:25]:
            A(f"| {r['material_grade']} | {r['thickness_mm']} | {r['plate_class']} | "
              f"{r['sample_count']} | {r['median_price_per_kg']} | {r['min_price_per_kg']} | "
              f"{r['max_price_per_kg']} | {r['median_price_per_m2']} |")
        A("")
        A(f"### SS400 代表参考kg単価（t4.5 / t6 / t9 / t12、税率{rate:.0%}）")
        for tk in ("4.5", "6", "9", "12"):
            hits = [r for r in plate_ref_summary
                    if r["material_grade"] == "SS400" and r["thickness_mm"] == tk]
            if hits:
                best = min(hits, key=lambda r: prio.get(r["plate_class"], 9))
                ex = best["median_price_per_kg"]
                inc = tx.inc_of(ex, rate)
                A(f"- SS400 t{tk}: 参考kg単価 税抜¥{ex}/kg → 税込¥{inc}/kg "
                  f"({best['plate_class']}, n={best['sample_count']})")
            else:
                A(f"- SS400 t{tk}: 参考データなし")
        A("")
    A(f"## 消費税の扱い（税率 {rate:.0%}）")
    A("- 既存の単価列（latest_unit_price / price_per_m / price_per_kg 等）は**税抜**。")
    A("- `*_inc_tax` 列が税込標準値、`*_tax` が消費税額。内部計算は税抜基準で最後に加税。")
    A("- layer_mapping の unit_price は**税抜**で保持（二重課税防止）。詳細は docs/tax-handling.md。")
    A("")
    A("## 外れ値候補 (outlier_items, 上位10)")
    for r in tables["outlier_items"][:10]:
        A(f"- {r['normalized_spec']}: {r['warning']} "
          f"(latest ¥{r['latest_unit_price']}, n={r['sample_count']})")
    if not tables["outlier_items"]:
        A("- なし")
    A("")
    A("## Rhinoレイヤー提案に使えない理由 (unmapped_reason_analysis)")
    for r in tables["unmapped_reason_analysis"]:
        A(f"- {r['label']}: spec_key {r['total_spec_keys']}件中 生材{r['usable_base']} / "
          f"{r['main_reason_no_mapping']}")
    A("")
    A("## 生材候補として安全に使えるもの / 使えないもの")
    A(f"- 安全に使える(ready): {len(ready_master)}件 — 定尺長・重量から単価換算でき、サンプル2件以上")
    A(f"- 人間確認で使える(usable_with_review): {len(usable_master)-len(ready_master)}件")
    A(f"- 生材単価に使わない(not_for_base_material/plate/加工品): "
      f"{sum(1 for m in master if m['usability']==U_NOT_BASE)}件")
    A(f"- JIS重量表が必要(needs_jis_master): "
      f"{sum(1 for m in master if m['usability']==U_NEEDS_JIS)}件")
    A(f"- データ不足(insufficient_data): "
      f"{sum(1 for m in master if m['usability']==U_INSUFFICIENT)}件")
    A("")
    A("## 注意（方針）")
    A("- 生材単価と加工品単価は混ぜない。加工品・切板は削除せず参考として残す。")
    A("- price_per_m / price_per_kg は spec_key の定尺長と体積式による自動算出。最終確定は人間。")
    A("- H形鋼・チャンネル・アングルの重量はJIS規格表が必要（price_per_kgは出さない）。")
    A("")
    A("## 関連CSV")
    A("- `toko_practical_price_master.csv`（実用単価マスター）")
    A("- `plate_reference_price.csv`（板材参考kg単価）")
    A("- `toko_price_analysis_tables/`（カテゴリ別分析テーブル群）")
    return "\n".join(L) + "\n"


def write_report(path: str, text: str) -> None:
    import os
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
