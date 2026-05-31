"""Rhinoレイヤー見積エンジン。

入力: layer_summary 行（数量根拠）＋ layer_mapping 行（人間が確定した計算ルール）
   ＋ 任意で cost_items（加工費等）／PDF単価DB（候補・補助）。
出力: estimate_result 行 と estimate_summary 行。

設計原則:
  - 計算の正は layer_mapping。自動推定は補助。
  - 単価決定優先: mapping > manual_prices > PDF DB完全一致 > PDF DB近似 > kg単価中央値 > unknown。
  - 根拠が弱い項目は needs_review / warning / accuracy_level で必ず可視化。
  - エラーで止めず、未確定はレビュー対象として出力。
"""

from __future__ import annotations

import math
import re
import statistics
from typing import Optional

from . import csv_utils as cu
from . import layer_mapping as lm
from . import cost_items as ci
from . import estimate as pdf_est
from . import settings as tx
from .models import MaterialRequest


# 注: unit_price / estimated_amount は「税抜」。estimated_amount_inc_tax が税込。
ESTIMATE_RESULT_FIELDS = (
    "source_type",
    "layer_name",
    "item_name",
    "calc_type",
    "material_category",
    "material_grade",
    "spec_text",
    "basis_quantity",
    "basis_unit",
    "object_count",
    "raw_area_m2",
    "raw_length_m",
    "raw_volume_mm3",
    "thickness_mm",
    "density_g_cm3",
    "estimated_weight_kg",
    "waste_rate",
    "adjusted_quantity",
    "unit_price",
    "price_unit",
    "pricing_mode",
    "selected_unit_price",
    "selected_price_basis",
    "estimated_amount",
    "estimated_amount_ex_tax",
    "tax_rate",
    "estimated_tax_amount",
    "estimated_amount_inc_tax",
    "price_source",
    "accuracy_level",
    "needs_review",
    "warning",
    "notes",
)

ESTIMATE_SUMMARY_FIELDS = (
    "category",
    "subtotal_amount",
    "subtotal_amount_ex_tax",
    "tax_rate",
    "tax_amount",
    "subtotal_amount_inc_tax",
    # 価格レンジ別小計（R6.3）
    "recommended_subtotal_ex_tax",
    "recommended_subtotal_inc_tax",
    "conservative_subtotal_ex_tax",
    "conservative_subtotal_inc_tax",
    "selected_subtotal_ex_tax",
    "selected_subtotal_inc_tax",
    "item_count",
    "needs_review_count",
    "warning_count",
    "notes",
)

# ユーザーが最初に見る「何がいくらか」一覧（税込を見やすく、税抜・税額も併記）
WHAT_COSTS_FIELDS = (
    "layer_name",
    "item_name",
    "calc_type",
    "material_category",
    "spec_text",
    "basis_quantity",
    "basis_unit",
    "total_volume_mm3",
    "estimated_weight_kg",
    "unit_price_ex_tax",
    "unit_price_inc_tax",
    "price_unit",
    "pricing_mode",
    "selected_price_basis",
    "estimated_amount_ex_tax",
    "estimated_tax_amount",
    "estimated_amount_inc_tax",
    # 価格レンジ別金額（R6.3）
    "recommended_amount_ex_tax",
    "recommended_amount_inc_tax",
    "conservative_amount_ex_tax",
    "conservative_amount_inc_tax",
    "selected_amount_ex_tax",
    "selected_amount_inc_tax",
    "price_range_note",
    "price_source",
    "accuracy_level",
    "needs_review",
    "warning",
    "next_action",
)

DEFAULT_DENSITY = 7.85
DEFAULT_STOCK_LENGTH_MM = 6000.0

# 価格決定で単価が必須となる calc_type
_PRICE_REQUIRED = {
    lm.CALC_AREA_TO_WEIGHT, lm.CALC_VOLUME_TO_WEIGHT, lm.CALC_CURVE_TO_STOCK,
    lm.CALC_CURVE_TO_METER, lm.CALC_OBJECT_COUNT, lm.CALC_MANUAL_QTY,
}


# ============================================================
# 公開エントリ
# ============================================================

def estimate_layers(summary_rows: list[dict], mapping_rows: list[dict],
                    cost_rows: Optional[list[dict]] = None,
                    db_conn=None, manual_prices: Optional[list[dict]] = None,
                    tax_rate: float = tx.DEFAULT_TAX_RATE) -> tuple[list[dict], list[dict]]:
    """見積結果行と総括行を返す。金額は税抜基準、税は最後に加える。"""
    s_index = {s.get("layer_name", ""): s for s in summary_rows}
    mapped = set()
    results: list[dict] = []

    for m in mapping_rows:
        layer = m.get("layer_name", "")
        mapped.add(layer)
        results.append(_estimate_mapping_row(m, s_index.get(layer), db_conn, manual_prices))

    # mapping に無いレイヤーは止めずに needs_review で出す
    for s in summary_rows:
        if s.get("layer_name", "") not in mapped:
            results.append(_unmapped_row(s))

    for c in (cost_rows or []):
        results.append(_cost_row(c))

    apply_tax_to_results(results, tax_rate)
    return results, build_estimate_summary(results, tax_rate)


def _set_range_amounts(r: dict, pricing) -> None:
    """選択/推奨(中央値)/安全側(最大値)の金額(税抜)を内部フィールドに格納する。"""
    sel = r.get("estimated_amount")
    sel = sel if isinstance(sel, (int, float)) else None
    qty = r.get("adjusted_quantity")
    qty = qty if isinstance(qty, (int, float)) else None
    rec = con = sel
    note = ""
    if pricing and sel is not None and qty is not None:
        rec_up = pricing.get("recommended")
        con_up = pricing.get("conservative")
        if rec_up is not None:
            rec = round(qty * rec_up)
        if con_up is not None:
            con = round(qty * con_up)
        note = (f"mode={pricing.get('mode')} 中央{rec_up}/最大{con_up} "
                f"(基準:{pricing.get('basis')})")
    r["_selected_amount"] = sel
    r["_recommended_amount"] = rec
    r["_conservative_amount"] = con
    r["_price_range_note"] = note


def apply_tax_to_results(results: list[dict], tax_rate: float = tx.DEFAULT_TAX_RATE) -> None:
    """各結果行の estimated_amount(税抜)から税抜・税額・税込列を埋める（in-place）。"""
    rate = tx.normalize_rate(tax_rate)
    for r in results:
        ex = r.get("estimated_amount")
        r["estimated_amount_ex_tax"] = cu._cell(ex) if ex not in (None, "") else ""
        r["tax_rate"] = rate
        r["estimated_tax_amount"] = cu._cell(tx.tax_of(ex, rate)) if ex not in (None, "") else ""
        r["estimated_amount_inc_tax"] = cu._cell(tx.inc_of(ex, rate)) if ex not in (None, "") else ""


# ============================================================
# レイヤー（mapping）行の計算
# ============================================================

def _estimate_mapping_row(m: dict, s: Optional[dict], db_conn, manual_prices) -> dict:
    layer = m.get("layer_name", "")
    calc = (m.get("calc_type", "") or "").strip()
    enabled = cu.to_bool(m.get("enabled", ""), default=True)
    r = _blank_result("rhino_layer", layer)
    r["calc_type"] = calc
    r["item_name"] = m.get("spec_text", "") or layer
    r["material_category"] = m.get("material_category", "")
    r["material_grade"] = m.get("material_grade", "")
    r["spec_text"] = m.get("spec_text", "")
    r["price_unit"] = m.get("price_unit", "")
    r["notes"] = m.get("notes", "")

    # 数量根拠（summary 由来）
    area_m2 = cu.to_float(s.get("total_area_m2")) if s else None
    volume_mm3 = cu.to_float(s.get("total_volume_mm3")) if s else None
    curve_m = cu.to_float(s.get("total_curve_length_m")) if s else None
    obj_count = cu.to_int(s.get("object_count")) if s else None
    r["raw_area_m2"] = area_m2
    r["raw_length_m"] = curve_m
    r["raw_volume_mm3"] = volume_mm3
    r["object_count"] = obj_count

    warnings: list[str] = []
    if s is None and calc not in (lm.CALC_FIXED_AMOUNT, lm.CALC_MANUAL_QTY, lm.CALC_IGNORE):
        warnings.append("layer_summaryに該当レイヤーなし(数量根拠なし)")

    # ignore / 無効
    if not enabled or calc == lm.CALC_IGNORE:
        return _make_ignored(r, "enabled=false" if not enabled else "calc_type=ignore")

    if calc not in lm.CALC_TYPES:
        r["accuracy_level"] = "unknown"
        r["needs_review"] = "true"
        warnings.append(f"未知のcalc_type: '{calc}'")
        r["warning"] = "; ".join(warnings)
        r["_summary_category"] = "unknown"
        return r

    waste = cu.to_float(m.get("waste_rate"))
    if waste is None:
        waste = 1.0
    r["waste_rate"] = waste
    thickness = cu.to_float(m.get("thickness_mm"))
    density = cu.to_float(m.get("density_g_cm3"))

    # 単価解決: pricing_mode/価格レンジがあればそれを採用、無ければ従来ロジック
    pricing = lm.resolve_pricing(m)
    if pricing is not None and pricing["selected"] is not None:
        unit_price = pricing["selected"]
        price_source = m.get("price_range_source", "") or f"range:{pricing['basis']}"
        accuracy = "range_master"
        r["pricing_mode"] = pricing["mode"]
        r["selected_unit_price"] = unit_price
        r["selected_price_basis"] = pricing["basis"]
    else:
        unit_price, price_source, accuracy = _resolve_price(m, calc, db_conn, manual_prices)
        r["pricing_mode"] = (m.get("pricing_mode", "") or "")
        r["selected_unit_price"] = unit_price
        r["selected_price_basis"] = "mapping.unit_price" if unit_price is not None else ""
    r["unit_price"] = unit_price
    r["price_source"] = price_source
    r["accuracy_level"] = accuracy
    r["_pricing"] = pricing

    # price_unit と calc_type の整合チェック
    _check_price_unit(calc, m.get("price_unit", ""), warnings)

    needs_review = False
    weight_kg = None

    if calc == lm.CALC_AREA_TO_WEIGHT:
        if thickness is None:
            warnings.append("thickness_mm未指定(面積→重量に必須)")
            needs_review = True
        if density is None:
            density = DEFAULT_DENSITY
            warnings.append(f"density_g_cm3未指定→{DEFAULT_DENSITY}を仮定")
        if not area_m2:
            warnings.append("面積データなし(area=0)")
            needs_review = True
        if thickness and area_m2:
            weight_kg = area_m2 * thickness * density * waste  # area_m2*(t/1000)*density*1000
        r["thickness_mm"] = thickness
        r["density_g_cm3"] = density
        r["estimated_weight_kg"] = _r(weight_kg)
        r["basis_quantity"] = _r(area_m2)
        r["basis_unit"] = "m2"
        r["adjusted_quantity"] = _r(weight_kg)
        needs_review |= _apply_amount_by_unit(r, weight_kg, unit_price, warnings)

    elif calc == lm.CALC_VOLUME_TO_WEIGHT:
        if density is None:
            density = DEFAULT_DENSITY
            warnings.append(f"density_g_cm3未指定→{DEFAULT_DENSITY}を仮定")
        if not volume_mm3:
            warnings.append("体積データなし(volume=0)")
            needs_review = True
        if volume_mm3:
            weight_kg = volume_mm3 * density * 1e-6 * waste
        r["density_g_cm3"] = density
        r["estimated_weight_kg"] = _r(weight_kg)
        r["basis_quantity"] = _r(volume_mm3)
        r["basis_unit"] = "mm3"
        r["adjusted_quantity"] = _r(weight_kg)
        needs_review |= _apply_amount_by_unit(r, weight_kg, unit_price, warnings)

    elif calc == lm.CALC_CURVE_TO_STOCK:
        stock_len = cu.to_float(m.get("stock_length_mm"))
        if stock_len is None or stock_len <= 0:
            stock_len = DEFAULT_STOCK_LENGTH_MM
            warnings.append(f"stock_length_mm未指定→{DEFAULT_STOCK_LENGTH_MM:g}を仮定")
        count = None
        if not curve_m:
            warnings.append("曲線長データなし(length=0)")
            needs_review = True
        else:
            count = math.ceil(curve_m * 1000.0 / stock_len * waste)
        r["basis_quantity"] = _r(curve_m)
        r["basis_unit"] = "m"
        r["adjusted_quantity"] = count
        r["notes"] = _join_note(r["notes"], f"定尺{stock_len:g}mm")
        needs_review |= _apply_amount_by_unit(r, count, unit_price, warnings)

    elif calc == lm.CALC_CURVE_TO_METER:
        eff = None
        if not curve_m:
            warnings.append("曲線長データなし(length=0)")
            needs_review = True
        else:
            eff = curve_m * waste
        r["basis_quantity"] = _r(curve_m)
        r["basis_unit"] = "m"
        r["adjusted_quantity"] = _r(eff)
        needs_review |= _apply_amount_by_unit(r, eff, unit_price, warnings)

    elif calc == lm.CALC_OBJECT_COUNT:
        if obj_count is None:
            warnings.append("object_count根拠なし")
            needs_review = True
        r["basis_quantity"] = obj_count
        r["basis_unit"] = "個"
        r["adjusted_quantity"] = obj_count
        needs_review |= _apply_amount_by_unit(r, obj_count, unit_price, warnings)

    elif calc == lm.CALC_MANUAL_QTY:
        qty = cu.to_float(m.get("quantity_override"))
        if qty is None:
            warnings.append("quantity_override未指定")
            needs_review = True
        r["basis_quantity"] = _r(qty)
        r["basis_unit"] = m.get("price_unit", "") or "個"
        r["adjusted_quantity"] = _r(qty)
        needs_review |= _apply_amount_by_unit(r, qty, unit_price, warnings)

    elif calc == lm.CALC_FIXED_AMOUNT:
        fixed = cu.to_float(m.get("fixed_amount"))
        r["accuracy_level"] = "fixed"
        r["price_source"] = price_source or "fixed"
        if fixed is None:
            warnings.append("fixed_amount未指定")
            needs_review = True
        r["estimated_amount"] = _r(fixed)
        r["adjusted_quantity"] = 1

    _set_range_amounts(r, pricing)
    r["needs_review"] = "true" if needs_review else "false"
    r["warning"] = "; ".join(warnings)
    # fixed_amount レイヤーは費目（加工/運搬/設計/施工）として分類し、材料費と混ぜない
    if calc == lm.CALC_FIXED_AMOUNT:
        r["_summary_category"] = _fixed_layer_category(f"{layer} {m.get('spec_text','')} {m.get('notes','')}")
    else:
        r["_summary_category"] = "material"
    return r


def _fixed_layer_category(text: str) -> str:
    """fixed_amount レイヤー名から見積総括カテゴリを推定（加工費等を材料費と分離）。"""
    t = text or ""
    if any(h in t for h in ("運搬", "輸送", "配送")):
        return "transport"
    if "設計" in t:
        return "design"
    if any(h in t for h in ("施工", "取付", "据付", "現場")):
        return "installation"
    return "processing"


def _apply_amount_by_unit(r: dict, qty, unit_price, warnings: list) -> bool:
    """qty × unit_price を金額に。単価欠落や qty 欠落時は needs_review を返す。"""
    if unit_price is None:
        warnings.append("unit_price未指定(単価決定できず)")
        r["estimated_amount"] = None
        return True
    if qty is None:
        r["estimated_amount"] = None
        return True
    r["estimated_amount"] = _r(qty * unit_price)
    return False


# ============================================================
# 単価解決
# ============================================================

def _resolve_price(m: dict, calc: str, db_conn, manual_prices) -> tuple[Optional[float], str, str]:
    """優先順位に従い (unit_price, price_source, accuracy_level) を返す。"""
    # 1. layer_mapping の unit_price
    mp_price = cu.to_float(m.get("unit_price"))
    if mp_price is not None:
        return mp_price, (m.get("price_source") or "layer_mapping"), "manual_mapping"

    if calc == lm.CALC_FIXED_AMOUNT:
        return None, "", "fixed"

    # 2. manual_prices 完全一致
    if manual_prices:
        p = _match_manual_price(m, manual_prices)
        if p is not None:
            return p, "manual_prices", "manual_price"

    # 3-5. PDF過去単価DB（候補・補助）
    if db_conn is not None:
        category = m.get("material_category", "")
        if calc in (lm.CALC_AREA_TO_WEIGHT, lm.CALC_VOLUME_TO_WEIGHT):
            kg = _kg_price_median(db_conn, category, m.get("material_grade", ""))
            if kg is not None:
                return kg, "pdf_db:kg_median", "formula"
        else:
            price, src, acc = _match_pdf_piece(m, db_conn)
            if price is not None:
                return price, src, acc

    return None, "", "unknown"


def _match_manual_price(m: dict, manual_prices: list[dict]) -> Optional[float]:
    spec = (m.get("spec_text", "") or "").strip()
    cat = (m.get("material_category", "") or "").strip()
    grade = (m.get("material_grade", "") or "").strip().upper()
    for row in manual_prices:
        rp = cu.to_float(row.get("unit_price"))
        if rp is None:
            continue
        if spec and row.get("spec_text", "").strip() == spec:
            return rp
        if cat and row.get("material_category", "").strip() == cat:
            if not grade or row.get("material_grade", "").strip().upper() == grade:
                return rp
    return None


def _kg_price_median(db_conn, category: str, grade: str) -> Optional[float]:
    """同一カテゴリ(任意で同一素材)の過去レコードから kg単価中央値を推定。"""
    try:
        from . import database as db
        cands = db.fetch_by_category(db_conn, category)
    except Exception:
        return None
    prices = []
    for c in cands:
        if grade and c.get("material_grade") and str(c["material_grade"]).upper() != grade.upper():
            continue
        req = MaterialRequest(
            material_category=c.get("material_category", ""),
            diameter_mm=c.get("diameter_mm"), thickness_mm=c.get("thickness_mm"),
            width_mm=c.get("width_mm"), height_mm=c.get("height_mm"),
            length_mm=c.get("length_mm"), plate_width_mm=c.get("plate_width_mm"),
            plate_height_mm=c.get("plate_height_mm"),
        )
        w = pdf_est.estimate_weight_kg(req)
        up = c.get("unit_price")
        if w and up and w > 0:
            prices.append(up / w)
    return statistics.median(prices) if prices else None


def _match_pdf_piece(m: dict, db_conn) -> tuple[Optional[float], str, str]:
    try:
        from . import database as db
        cands = db.fetch_by_category(db_conn, m.get("material_category", ""))
    except Exception:
        return None, "", "unknown"
    req = MaterialRequest(
        material_category=m.get("material_category", ""),
        material_grade=m.get("material_grade", ""),
        diameter_mm=cu.to_float(m.get("diameter_mm")),
        thickness_mm=cu.to_float(m.get("thickness_mm")),
        width_mm=cu.to_float(m.get("width_mm")),
        height_mm=cu.to_float(m.get("height_mm")),
    )
    res = pdf_est.match_records(req, cands)
    if res["unit_price"] is not None and res["accuracy_level"] in ("exact", "close"):
        return res["unit_price"], f"pdf_db:{res['source_pdf']}", res["accuracy_level"]
    return None, "", "unknown"


def _check_price_unit(calc: str, price_unit: str, warnings: list) -> None:
    expected = lm.EXPECTED_PRICE_UNIT.get(calc)
    if expected is None or not price_unit:
        return
    pu = price_unit.strip()
    # 定尺は "6m" 等の N m 表記も許可
    if calc == lm.CALC_CURVE_TO_STOCK and re.fullmatch(r"\d+(\.\d+)?m", pu):
        return
    if pu not in expected:
        warnings.append(
            f"price_unit '{pu}' は calc_type '{calc}' と不整合(期待: {'/'.join(expected)})")


# ============================================================
# unmapped / ignored / cost
# ============================================================

def _unmapped_row(s: dict) -> dict:
    r = _blank_result("rhino_layer", s.get("layer_name", ""))
    r["item_name"] = s.get("layer_name", "")
    r["calc_type"] = ""
    r["raw_area_m2"] = cu.to_float(s.get("total_area_m2"))
    r["raw_length_m"] = cu.to_float(s.get("total_curve_length_m"))
    r["raw_volume_mm3"] = cu.to_float(s.get("total_volume_mm3"))
    r["object_count"] = cu.to_int(s.get("object_count"))
    r["accuracy_level"] = "unknown"
    r["needs_review"] = "true"
    r["warning"] = "layer_mapping未設定(計算ルール未確定)"
    r["notes"] = "mappingに未登録のレイヤー。init/update-layer-mappingで追加してください。"
    r["_summary_category"] = "unknown"
    return r


def _make_ignored(r: dict, reason: str) -> dict:
    r["accuracy_level"] = "ignored"
    r["source_type"] = "ignored"
    r["needs_review"] = "false"
    r["estimated_amount"] = ""
    r["notes"] = _join_note(r.get("notes", ""), f"対象外({reason})")
    r["_summary_category"] = "ignored"
    return r


def _cost_row(c: dict) -> dict:
    r = _blank_result("cost_item", "")
    name = c.get("item_name", "")
    cat = c.get("cost_category", "")
    calc = (c.get("calc_type", "") or "").strip() or "fixed_amount"
    r["item_name"] = name
    r["calc_type"] = calc
    r["spec_text"] = cat
    r["material_category"] = cat
    r["price_unit"] = c.get("unit", "")
    r["notes"] = c.get("notes", "")

    warnings: list[str] = []
    needs_review = False
    if calc == "fixed_amount":
        fixed = cu.to_float(c.get("fixed_amount"))
        if fixed is None:
            warnings.append("fixed_amount未指定")
            needs_review = True
        r["estimated_amount"] = _r(fixed)
        r["adjusted_quantity"] = 1
        r["accuracy_level"] = "fixed"
        r["price_source"] = "cost_items"
    else:  # quantity × unit_price
        qty = cu.to_float(c.get("quantity"))
        up = cu.to_float(c.get("unit_price"))
        if qty is None or up is None:
            warnings.append("quantity または unit_price 未指定")
            needs_review = True
        r["unit_price"] = up
        r["basis_quantity"] = _r(qty)
        r["adjusted_quantity"] = _r(qty)
        r["estimated_amount"] = _r(qty * up) if (qty is not None and up is not None) else None
        r["accuracy_level"] = "manual_price"
        r["price_source"] = "cost_items"

    r["needs_review"] = "true" if needs_review else "false"
    r["warning"] = "; ".join(warnings)
    r["_summary_category"] = ci.summary_category(cat)
    return r


# ============================================================
# 総括
# ============================================================

def build_estimate_summary(results: list[dict],
                           tax_rate: float = tx.DEFAULT_TAX_RATE) -> list[dict]:
    rate = tx.normalize_rate(tax_rate)
    order = ["material", "processing", "transport", "installation", "design", "ignored", "unknown"]
    buckets: dict[str, dict] = {}
    for r in results:
        cat = r.get("_summary_category", "unknown")
        b = buckets.setdefault(cat, {"subtotal": 0.0, "rec": 0.0, "con": 0.0,
                                     "n": 0, "review": 0, "warn": 0})
        amt = r.get("estimated_amount")
        if isinstance(amt, (int, float)):
            b["subtotal"] += amt
        # 価格レンジ別小計（内部フィールドが無ければ選択額にフォールバック）
        rec = r.get("_recommended_amount", amt)
        con = r.get("_conservative_amount", amt)
        if isinstance(rec, (int, float)):
            b["rec"] += rec
        if isinstance(con, (int, float)):
            b["con"] += con
        b["n"] += 1
        if str(r.get("needs_review")) == "true":
            b["review"] += 1
        if r.get("warning"):
            b["warn"] += 1

    def _tax_cols(b):
        ex = round(b["subtotal"])
        tax = tx.tax_of(ex, rate)            # 整数円なので ex+tax==inc が厳密成立
        rec = round(b["rec"])
        con = round(b["con"])
        return {
            "subtotal_amount": ex,
            "subtotal_amount_ex_tax": ex,
            "tax_rate": rate,
            "tax_amount": tax,
            "subtotal_amount_inc_tax": ex + (tax or 0),
            "selected_subtotal_ex_tax": ex,
            "selected_subtotal_inc_tax": ex + (tax or 0),
            "recommended_subtotal_ex_tax": rec,
            "recommended_subtotal_inc_tax": rec + (tx.tax_of(rec, rate) or 0),
            "conservative_subtotal_ex_tax": con,
            "conservative_subtotal_inc_tax": con + (tx.tax_of(con, rate) or 0),
        }

    rows = []
    for cat in order + [c for c in buckets if c not in order]:
        if cat not in buckets:
            continue
        b = buckets[cat]
        note = ""
        if cat == "unknown" and b["n"]:
            note = "根拠不足。mapping/単価の確定が必要。"
        if cat == "ignored":
            note = "見積対象外。"
        row = {
            "category": cat,
            "item_count": b["n"],
            "needs_review_count": b["review"],
            "warning_count": b["warn"],
            "notes": note,
        }
        row.update(_tax_cols(b))
        rows.append(row)
    # 総計行（total_ex / total_tax / total_inc を税列で表現）
    tot = {"subtotal": 0.0, "rec": 0.0, "con": 0.0}
    for c, b in buckets.items():
        if c in ("ignored",):
            continue
        tot["subtotal"] += b["subtotal"]
        tot["rec"] += b["rec"]
        tot["con"] += b["con"]
    total_row = {
        "category": "TOTAL(除ignored)",
        "item_count": sum(b["n"] for b in buckets.values()),
        "needs_review_count": sum(b["review"] for b in buckets.values()),
        "warning_count": sum(b["warn"] for b in buckets.values()),
        "notes": f"ignoredを除く合計。中央値/最大値/選択を併記。税抜→消費税{rate:.0%}→税込。概算。",
    }
    total_row.update(_tax_cols(tot))
    rows.append(total_row)
    return rows


# ============================================================
# 何がいくらか（what_costs_how_much）
# ============================================================

def build_what_costs(results: list[dict],
                     tax_rate: float = tx.DEFAULT_TAX_RATE) -> list[dict]:
    """ユーザーが最初に見る『何がいくらか』一覧。金額の付く行のみ、税込を見やすく。"""
    rate = tx.normalize_rate(tax_rate)
    rows = []
    for r in results:
        if r.get("_summary_category") == "ignored":
            continue
        amt = r.get("estimated_amount")
        if not isinstance(amt, (int, float)):
            continue
        up = r.get("unit_price")
        rec = r.get("_recommended_amount", amt)
        con = r.get("_conservative_amount", amt)
        sel = r.get("_selected_amount", amt)
        rows.append({
            "layer_name": r.get("layer_name", ""),
            "item_name": r.get("item_name", ""),
            "calc_type": r.get("calc_type", ""),
            "material_category": r.get("material_category", ""),
            "spec_text": r.get("spec_text", ""),
            "basis_quantity": r.get("adjusted_quantity", r.get("basis_quantity", "")),
            "basis_unit": r.get("basis_unit", ""),
            "total_volume_mm3": (str(int(round(_vol))) if (_vol := cu.to_float(r.get("raw_volume_mm3"))) else ""),
            "estimated_weight_kg": cu._cell(r.get("estimated_weight_kg", "")),
            "unit_price_ex_tax": cu._cell(up) if up not in (None, "") else "",
            "unit_price_inc_tax": cu._cell(tx.inc_of(up, rate)) if up not in (None, "") else "",
            "price_unit": r.get("price_unit", ""),
            "pricing_mode": r.get("pricing_mode", ""),
            "selected_price_basis": r.get("selected_price_basis", ""),
            "estimated_amount_ex_tax": cu._cell(amt),
            "estimated_tax_amount": cu._cell(tx.tax_of(amt, rate)),
            "estimated_amount_inc_tax": cu._cell(tx.inc_of(amt, rate)),
            "recommended_amount_ex_tax": cu._cell(rec),
            "recommended_amount_inc_tax": cu._cell(tx.inc_of(rec, rate)),
            "conservative_amount_ex_tax": cu._cell(con),
            "conservative_amount_inc_tax": cu._cell(tx.inc_of(con, rate)),
            "selected_amount_ex_tax": cu._cell(sel),
            "selected_amount_inc_tax": cu._cell(tx.inc_of(sel, rate)),
            "price_range_note": r.get("_price_range_note", ""),
            "price_source": r.get("price_source", ""),
            "accuracy_level": r.get("accuracy_level", ""),
            "needs_review": r.get("needs_review", ""),
            "warning": r.get("warning", ""),
            "next_action": _next_action(r),
        })
    rows.sort(key=lambda x: -(cu.to_float(x["estimated_amount_ex_tax"]) or 0))
    return rows


def _next_action(r: dict) -> str:
    """ユーザーが次に何をすべきかの一言。"""
    if str(r.get("needs_review")) == "true":
        if (r.get("unit_price") in (None, "")):
            return "単価未確定: mapping UIでkg単価/pricing_modeを設定"
        return "要確認: 数量根拠・単価を確認"
    return "OK（参考値。発注前に実見積で確認）"


def write_what_costs(path: str, rows: list[dict]) -> int:
    return cu.write_dicts(path, WHAT_COSTS_FIELDS, rows)


# ============================================================
# 補助
# ============================================================

def _blank_result(source_type: str, layer: str) -> dict:
    r = {f: "" for f in ESTIMATE_RESULT_FIELDS}
    r["source_type"] = source_type
    r["layer_name"] = layer
    r["needs_review"] = "false"
    r["accuracy_level"] = "unknown"
    r["_summary_category"] = "material"
    return r


def _r(v):
    if v is None:
        return None
    if isinstance(v, float):
        return round(v, 3)
    return v


def _join_note(a: str, b: str) -> str:
    a = a or ""
    if not b:
        return a
    return f"{a}; {b}".strip("; ") if a else b


def write_results(path: str, rows: list[dict]) -> int:
    return cu.write_dicts(path, ESTIMATE_RESULT_FIELDS, rows)


def write_summary(path: str, rows: list[dict]) -> int:
    return cu.write_dicts(path, ESTIMATE_SUMMARY_FIELDS, rows)
