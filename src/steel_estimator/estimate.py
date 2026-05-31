"""重量計算と概算見積エンジン（v1）。

方針:
  - 過去PDF抽出の単価を材料マスターとして利用（quote_date / vendor 紐付け）。
  - 精度区分 exact / close / formula / unknown。
  - 材料費のみ。加工費・送料・消費税は混ぜない（別フェーズ）。
  - 重量式は鉄前提（密度 7.85 g/cm³）。SUS/アルミ・アングル/チャンネルは単価参照優先。
"""

from __future__ import annotations

import math
import statistics
from typing import Optional

from . import DENSITY_STEEL_G_CM3
from .models import MaterialCategory as C, MaterialRequest


# ============================================================
# 重量計算（戻り値 kg）。すべての寸法入力は mm。
# ============================================================

def weight_round_bar_kg(diameter_mm: float, length_mm: float,
                        density_g_cm3: float = DENSITY_STEEL_G_CM3) -> float:
    """丸棒: 体積 = π/4 · d² · L。"""
    r_cm = (diameter_mm / 10.0) / 2.0
    l_cm = length_mm / 10.0
    vol_cm3 = math.pi * r_cm * r_cm * l_cm
    return vol_cm3 * density_g_cm3 / 1000.0


def weight_round_pipe_kg(diameter_mm: float, thickness_mm: float, length_mm: float,
                         density_g_cm3: float = DENSITY_STEEL_G_CM3) -> float:
    """丸パイプ: 外径 d・肉厚 t の中空円筒。内径 = d - 2t。"""
    do_cm = diameter_mm / 10.0
    di_cm = (diameter_mm - 2.0 * thickness_mm) / 10.0
    if di_cm < 0:
        di_cm = 0.0
    l_cm = length_mm / 10.0
    vol_cm3 = math.pi / 4.0 * (do_cm ** 2 - di_cm ** 2) * l_cm
    return vol_cm3 * density_g_cm3 / 1000.0


def weight_square_pipe_kg(width_mm: float, height_mm: float, thickness_mm: float,
                          length_mm: float,
                          density_g_cm3: float = DENSITY_STEEL_G_CM3) -> float:
    """角パイプ: 外形 W×H・肉厚 t の中空角筒。"""
    w_cm, h_cm, t_cm = width_mm / 10.0, height_mm / 10.0, thickness_mm / 10.0
    l_cm = length_mm / 10.0
    inner_w = max(w_cm - 2.0 * t_cm, 0.0)
    inner_h = max(h_cm - 2.0 * t_cm, 0.0)
    vol_cm3 = (w_cm * h_cm - inner_w * inner_h) * l_cm
    return vol_cm3 * density_g_cm3 / 1000.0


def weight_plate_kg(thickness_mm: float, width_mm: float, height_mm: float,
                    density_g_cm3: float = DENSITY_STEEL_G_CM3) -> float:
    """鉄板: t × 幅 × 高 の直方体。"""
    t_cm, w_cm, h_cm = thickness_mm / 10.0, width_mm / 10.0, height_mm / 10.0
    vol_cm3 = t_cm * w_cm * h_cm
    return vol_cm3 * density_g_cm3 / 1000.0


def estimate_weight_kg(req: MaterialRequest,
                       density_g_cm3: float = DENSITY_STEEL_G_CM3) -> Optional[float]:
    """MaterialRequest から重量を推定。算定不能なら None。

    アングル/チャンネル/H形鋼はJIS表が必要なため v1 では None（単価参照優先）。
    """
    cat = req.material_category
    try:
        if cat == C.ROUND_BAR and req.diameter_mm and req.length_mm:
            return weight_round_bar_kg(req.diameter_mm, req.length_mm, density_g_cm3)
        if cat == C.ROUND_PIPE and req.diameter_mm and req.thickness_mm and req.length_mm:
            return weight_round_pipe_kg(req.diameter_mm, req.thickness_mm, req.length_mm, density_g_cm3)
        if cat == C.SQUARE_PIPE and req.width_mm and req.height_mm and req.thickness_mm and req.length_mm:
            return weight_square_pipe_kg(req.width_mm, req.height_mm, req.thickness_mm,
                                         req.length_mm, density_g_cm3)
        if cat == C.PLATE and req.thickness_mm:
            w = req.plate_width_mm or req.width_mm
            h = req.plate_height_mm or req.length_mm or req.height_mm
            if w and h:
                return weight_plate_kg(req.thickness_mm, w, h, density_g_cm3)
        if cat == C.FLAT_BAR and req.thickness_mm and req.width_mm and req.length_mm:
            return weight_plate_kg(req.thickness_mm, req.width_mm, req.length_mm, density_g_cm3)
    except (TypeError, ValueError):
        return None
    return None


# ============================================================
# 単価統計
# ============================================================

def summarize_prices(prices: list[float]) -> dict:
    """過去単価リストから 最新は呼び出し側、ここでは median/mean/max/min/n。"""
    clean = [p for p in prices if p is not None]
    if not clean:
        return {"n": 0, "median": None, "mean": None, "max": None, "min": None}
    return {
        "n": len(clean),
        "median": statistics.median(clean),
        "mean": statistics.fmean(clean),
        "max": max(clean),
        "min": min(clean),
    }


# ============================================================
# マッチング（精度区分）
# ============================================================

def _approx(a: Optional[float], b: Optional[float], tol: float = 0.10) -> bool:
    """相対誤差 tol 以内（既定10%）。両方Noneなら一致扱い、片方Noneは不一致。"""
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    if b == 0:
        return a == 0
    return abs(a - b) / abs(b) <= tol


def match_records(req: MaterialRequest, candidates: list[dict]) -> dict:
    """過去レコード(dict)群から最良マッチを返す。

    candidates は DB 行（material_category, 寸法, unit_price, quote_date, ... を含む dict）。
    戻り: {accuracy_level, unit_price, source_pdf, vendor, quote_date, basis, warning}
    """
    same_cat = [c for c in candidates if c.get("material_category") == req.material_category]

    # exact: 規格・主要寸法・長さが一致
    exact = [c for c in same_cat if _matches_exact(req, c)]
    if exact:
        best = _latest(exact)
        return _result("exact", best,
                       basis=f"同一規格の過去見積({len(exact)}件)")

    # close: 同一カテゴリ・近似寸法
    close = [c for c in same_cat if _matches_close(req, c)]
    if close:
        best = _latest(close)
        prices = [c.get("unit_price") for c in close if c.get("unit_price") is not None]
        stats = summarize_prices(prices)
        return _result("close", best,
                       basis=f"近似寸法の過去見積({stats['n']}件) median={_fmt(stats['median'])}",
                       warning="寸法が近似のため誤差あり")
    return {"accuracy_level": "unknown", "unit_price": None, "source_pdf": "",
            "vendor": "", "quote_date": "", "basis": "根拠となる過去見積なし",
            "warning": "該当データ不足"}


def _matches_exact(req: MaterialRequest, c: dict) -> bool:
    if req.material_grade and c.get("material_grade") and \
       req.material_grade.upper() != str(c.get("material_grade")).upper():
        return False
    keys = _dim_keys(req.material_category)
    return all(_approx(getattr(req, k), c.get(k), tol=0.001) for k in keys)


def _matches_close(req: MaterialRequest, c: dict) -> bool:
    keys = _dim_keys(req.material_category)
    return all(_approx(getattr(req, k), c.get(k), tol=0.15) for k in keys if getattr(req, k) is not None)


def _dim_keys(category: str) -> tuple:
    if category in (C.ROUND_PIPE, C.ROLLED):
        return ("diameter_mm", "thickness_mm", "length_mm")
    if category == C.ROUND_BAR:
        return ("diameter_mm", "length_mm")
    if category in (C.SQUARE_PIPE, C.ANGLE, C.CHANNEL):
        return ("width_mm", "height_mm", "thickness_mm", "length_mm")
    if category == C.FLAT_BAR:
        return ("thickness_mm", "width_mm", "length_mm")
    if category == C.PLATE:
        return ("thickness_mm", "plate_width_mm", "plate_height_mm")
    return ("thickness_mm",)


def _latest(cands: list[dict]) -> dict:
    return max(cands, key=lambda c: c.get("quote_date") or "")


def _result(level, best, basis="", warning="") -> dict:
    return {
        "accuracy_level": level,
        "unit_price": best.get("unit_price"),
        "source_pdf": best.get("source_pdf_filename", ""),
        "vendor": best.get("vendor_name", ""),
        "quote_date": best.get("quote_date", ""),
        "basis": basis,
        "warning": warning,
    }


def _fmt(v) -> str:
    return f"{v:,.0f}" if isinstance(v, (int, float)) else ""
