"""板厚別・鋼材種別ごとの価格レンジマスター（Phase R6.3）。

目的:
  - 取得済みの板材(切板/型切)・鋼材データから、板厚/寸法ごとに
    「中央値〜最大値」の価格レンジを作る。
  - recommended=median（通常見積）。conservative=安全側＝中央値を基準に最低1.3倍・
    最大2.0倍へ範囲制限した値（外れ値=最大値の過大評価を抑制。safe_conservative）。
  - 自動確定はしない。editable=true で人間が手入力変更できる「推奨初期値」。
  - 税抜が内部基準、税込は併記（*_inc_tax）。

入力:
  - 板材: plate_reference_price.csv（外接矩形ベースの参考価格、usable_as_reference=true）
  - 鋼材: toko_practical_price_master.csv（spec_key別の単価・換算、min/max_unit_price 付き）
"""

from __future__ import annotations

import statistics

from . import csv_utils as cu
from . import candidate_prices as cp
from . import settings as tx
from . import price_analysis as pa
from .models import MaterialCategory as C


# 優先的に揃えたい板厚（mm）
TARGET_THICKNESSES = [1.6, 2.3, 3.2, 4.5, 6, 9, 12, 16, 19, 22, 25, 32]

# 鋼材レンジ対象カテゴリ
SHAPE_CATEGORIES = (
    C.SQUARE_PIPE, C.ROUND_PIPE, C.FLAT_BAR, C.ROUND_BAR,
    C.ANGLE, C.SQUARE_BAR, C.H_BEAM, C.CHANNEL,
)

PLATE_REF_WARNING = pa.PLATE_REF_WARNING


PLATE_RANGE_FIELDS = (
    "material_grade", "thickness_mm", "plate_class", "sample_count", "latest_quote_date",
    "min_price_per_kg_ex_tax", "median_price_per_kg_ex_tax",
    "average_price_per_kg_ex_tax", "max_price_per_kg_ex_tax",
    "min_price_per_kg_inc_tax", "median_price_per_kg_inc_tax",
    "average_price_per_kg_inc_tax", "max_price_per_kg_inc_tax",
    "min_price_per_m2_ex_tax", "median_price_per_m2_ex_tax",
    "average_price_per_m2_ex_tax", "max_price_per_m2_ex_tax",
    "min_price_per_m2_inc_tax", "median_price_per_m2_inc_tax",
    "average_price_per_m2_inc_tax", "max_price_per_m2_inc_tax",
    "recommended_price_per_kg_ex_tax", "conservative_price_per_kg_ex_tax",
    "recommended_price_per_kg_inc_tax", "conservative_price_per_kg_inc_tax",
    "default_pricing_mode", "editable", "confidence", "warning", "notes",
)

STEEL_SHAPE_RANGE_FIELDS = (
    "material_category", "material_grade", "shape_group", "normalized_spec", "spec_key",
    "diameter_mm", "width_mm", "height_mm", "thickness_mm", "length_mm", "stock_length_mm",
    "sample_count", "latest_quote_date",
    "min_unit_price_ex_tax", "median_unit_price_ex_tax",
    "average_unit_price_ex_tax", "max_unit_price_ex_tax",
    "min_unit_price_inc_tax", "median_unit_price_inc_tax",
    "average_unit_price_inc_tax", "max_unit_price_inc_tax",
    "min_price_per_m_ex_tax", "median_price_per_m_ex_tax",
    "average_price_per_m_ex_tax", "max_price_per_m_ex_tax",
    "min_price_per_m_inc_tax", "median_price_per_m_inc_tax",
    "average_price_per_m_inc_tax", "max_price_per_m_inc_tax",
    "min_price_per_kg_ex_tax", "median_price_per_kg_ex_tax",
    "average_price_per_kg_ex_tax", "max_price_per_kg_ex_tax",
    "min_price_per_kg_inc_tax", "median_price_per_kg_inc_tax",
    "average_price_per_kg_inc_tax", "max_price_per_kg_inc_tax",
    "recommended_unit_price_ex_tax", "conservative_unit_price_ex_tax",
    "recommended_price_per_m_ex_tax", "conservative_price_per_m_ex_tax",
    "recommended_price_per_kg_ex_tax", "conservative_price_per_kg_ex_tax",
    "default_pricing_mode", "editable", "usability", "confidence", "warning", "notes",
)


# ============================================================
# 統計ヘルパー
# ============================================================

def _f(v):
    return cu.to_float(v)


def _stat4(vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    return {
        "min": min(vals), "median": statistics.median(vals),
        "average": statistics.fmean(vals), "max": max(vals),
    }


# 安全側単価の範囲制限（外れ値による過大評価を避ける）
SAFE_MIN_FACTOR = 1.3   # 安全側は最低でも中央値の1.3倍
SAFE_MAX_FACTOR = 2.0   # 安全側は最大でも中央値の2.0倍


def safe_conservative(median_v, max_v):
    """安全側単価 = 中央値を基準に [中央値×1.3, 中央値×2.0] へ範囲制限した値。

    safe = max(max_v, median×1.3); safe = min(safe, median×2.0)。
    - 最大値が中央値の1.3〜2.0倍 → 最大値を採用
    - 最大値が中央値の1.3倍未満（同値含む）→ 中央値×1.3
    - 最大値が中央値の2.0倍超 → 中央値×2.0（外れ値を抑制）
    例: 中央値300/最大1420→600、300/300→390、300/350→390、300/500→500、300/700→600。
    """
    if median_v is None:
        return max_v
    lo = median_v * SAFE_MIN_FACTOR
    hi = median_v * SAFE_MAX_FACTOR
    base = max_v if max_v is not None else lo
    return min(max(base, lo), hi)


def _stat_safe_con(stat):
    """_stat4 の dict から安全側(clamp済)を返す。stat 無しは None。"""
    if not stat:
        return None
    return safe_conservative(stat.get("median"), stat.get("max"))


def _fmtnum(v, nd):
    return "" if v is None else f"{round(v, nd):g}"


def _range_cols(metric: str, stat, rate, nd=1) -> dict:
    """{min/median/average/max}_{metric}_{ex_tax,inc_tax} を返す（_tax列は出さない）。"""
    out = {}
    for k in ("min", "median", "average", "max"):
        v = stat[k] if stat else None
        ex = _fmtnum(v, nd)
        ex_s, _tax_s, inc_s = tx.triple(ex, rate) if ex != "" else ("", "", "")
        out[f"{k}_{metric}_ex_tax"] = ex_s
        out[f"{k}_{metric}_inc_tax"] = inc_s
    return out


def _scale_stat(stat, factor):
    if stat is None or factor is None:
        return None
    return {k: v * factor for k, v in stat.items()}


# ============================================================
# 板材の価格レンジマスター
# ============================================================

def build_plate_price_range_master(plate_ref_rows: list[dict],
                                   tax_rate: float = tx.DEFAULT_TAX_RATE) -> list[dict]:
    rate = tx.normalize_rate(tax_rate)
    groups: dict[tuple, list[dict]] = {}
    for r in plate_ref_rows:
        if r.get("usable_as_reference") != "true":
            continue
        key = (r.get("material_grade", ""), r.get("thickness_mm", ""), r.get("plate_class", ""))
        groups.setdefault(key, []).append(r)

    out = []
    for (grade, thick, pclass), members in groups.items():
        kg = _stat4([_f(m.get("price_per_kg")) for m in members])
        m2 = _stat4([_f(m.get("price_per_m2")) for m in members])
        if kg is None:
            continue
        latest = max(members, key=lambda m: m.get("quote_date") or "")
        row = {
            "material_grade": grade, "thickness_mm": thick, "plate_class": pclass,
            "sample_count": len(members),
            "latest_quote_date": latest.get("quote_date", ""),
            "default_pricing_mode": "median", "editable": "true",
            "confidence": 0.5 if pclass == pa.PLATE_RAW else 0.4,
            "warning": PLATE_REF_WARNING,
            "notes": "切板/型切由来の外接矩形ベース。通常=中央値/安全側=中央値の1.3〜2.0倍clamp。手入力変更可。",
        }
        row.update(_range_cols("price_per_kg", kg, rate, nd=1))
        row.update(_range_cols("price_per_m2", m2, rate, nd=0))
        # recommended=median, conservative=安全側(中央値×1.3〜2.0にclamp。外れ値抑制)
        kg_con = _stat_safe_con(kg)
        row["recommended_price_per_kg_ex_tax"] = _fmtnum(kg["median"], 1)
        row["conservative_price_per_kg_ex_tax"] = _fmtnum(kg_con, 1)
        row["recommended_price_per_kg_inc_tax"] = tx._fmt(tx.inc_of(kg["median"], rate))
        row["conservative_price_per_kg_inc_tax"] = tx._fmt(tx.inc_of(kg_con, rate))
        out.append(row)
    out.sort(key=lambda r: (_f(r["thickness_mm"]) or 0, r["material_grade"], r["plate_class"]))
    return out


def write_plate_price_range_master(path: str, rows: list[dict]) -> int:
    return cu.write_dicts(path, PLATE_RANGE_FIELDS, rows)


def missing_thicknesses(rows: list[dict], grade: str = "SS400") -> list[float]:
    have = {_f(r["thickness_mm"]) for r in rows if r.get("material_grade") == grade}
    return [t for t in TARGET_THICKNESSES if t not in have]


# ============================================================
# 鋼材種別の価格レンジマスター
# ============================================================

def build_steel_shape_price_range_master(master_rows: list[dict],
                                         tax_rate: float = tx.DEFAULT_TAX_RATE) -> list[dict]:
    rate = tx.normalize_rate(tax_rate)
    out = []
    for m in master_rows:
        cat = m.get("material_category", "")
        if cat not in SHAPE_CATEGORIES or m.get("candidate_class") == "plate_reference":
            continue
        parsed = cp.parse_spec_key(m.get("spec_key", ""))

        unit = _stat4([
            _f(m.get("min_unit_price")), _f(m.get("median_unit_price")),
            _f(m.get("average_unit_price")), _f(m.get("max_unit_price")),
        ])
        # min/median/average/max が個別に取れない場合は latest を中心に縮退
        if unit is None:
            lp = _f(m.get("latest_unit_price"))
            unit = {"min": lp, "median": lp, "average": lp, "max": lp} if lp is not None else None
        else:
            unit = {
                "min": _f(m.get("min_unit_price")),
                "median": _f(m.get("median_unit_price")) or _f(m.get("latest_unit_price")),
                "average": _f(m.get("average_unit_price")),
                "max": _f(m.get("max_unit_price")),
            }
            # 欠損は median で補完
            med = unit["median"]
            for k in ("min", "average", "max"):
                if unit[k] is None:
                    unit[k] = med
        if unit is None or unit.get("median") is None:
            continue

        length = parsed.get("length")
        weight = _f(m.get("estimated_weight_kg_per_stock"))
        factor_m = (1000.0 / length) if (length and length >= 1000) else None
        factor_kg = (1.0 / weight) if (weight and weight > 0) else None
        per_m = _scale_stat(unit, factor_m)
        per_kg = _scale_stat(unit, factor_kg)

        row = {
            "material_category": cat,
            "material_grade": m.get("material_grade", ""),
            "shape_group": pa.JP_LABEL.get(cat, cat),
            "normalized_spec": m.get("normalized_spec", ""),
            "spec_key": m.get("spec_key", ""),
            "diameter_mm": _g(parsed.get("diameter")),
            "width_mm": _g(parsed.get("width")),
            "height_mm": _g(parsed.get("height")),
            "thickness_mm": _g(parsed.get("thickness")),
            "length_mm": _g(parsed.get("length")),
            "stock_length_mm": m.get("stock_length_mm", ""),
            "sample_count": m.get("sample_count", ""),
            "latest_quote_date": m.get("latest_quote_date", ""),
            "default_pricing_mode": "median", "editable": "true",
            "usability": m.get("usability", ""),
            "confidence": m.get("confidence", ""),
            "warning": m.get("warning", ""),
            "notes": "通常=中央値/安全側=中央値の1.3〜2.0倍clamp。手入力変更可。既存単価列は税抜。",
        }
        row.update(_range_cols("unit_price", unit, rate, nd=0))
        row.update(_range_cols("price_per_m", per_m, rate, nd=1))
        row.update(_range_cols("price_per_kg", per_kg, rate, nd=1))
        # recommended=median / conservative=安全側(中央値×1.3〜2.0にclamp)（ex_taxのみ）
        row["recommended_unit_price_ex_tax"] = _fmtnum(unit["median"], 0)
        row["conservative_unit_price_ex_tax"] = _fmtnum(_stat_safe_con(unit), 0)
        row["recommended_price_per_m_ex_tax"] = _fmtnum(per_m["median"], 1) if per_m else ""
        row["conservative_price_per_m_ex_tax"] = _fmtnum(_stat_safe_con(per_m), 1) if per_m else ""
        row["recommended_price_per_kg_ex_tax"] = _fmtnum(per_kg["median"], 1) if per_kg else ""
        row["conservative_price_per_kg_ex_tax"] = _fmtnum(_stat_safe_con(per_kg), 1) if per_kg else ""
        out.append(row)
    out.sort(key=lambda r: (r["material_category"], r["spec_key"]))
    return out


def write_steel_shape_price_range_master(path: str, rows: list[dict]) -> int:
    return cu.write_dicts(path, STEEL_SHAPE_RANGE_FIELDS, rows)


def _g(v):
    return "" if v is None else f"{float(v):g}"


# ============================================================
# レポート
# ============================================================

def build_range_report(plate_rows: list[dict], shape_rows: list[dict],
                       tax_rate: float = tx.DEFAULT_TAX_RATE, now_str: str = "") -> str:
    rate = tx.normalize_rate(tax_rate)
    L = []
    A = L.append
    A("# 価格レンジマスター レポート（Phase R6.3）")
    A("")
    if now_str:
        A(f"- 実行: {now_str}")
    A(f"- 税率: {rate:.0%}（既存列は税抜、*_inc_tax が税込）")
    A(f"- 板材レンジ: {len(plate_rows)}件 / 鋼材レンジ: {len(shape_rows)}件")
    A("")
    A("## 中央値/最大値の使い分け")
    A("- **中央値(recommended)**: 通常見積の初期値。過去実績の代表値。")
    A("- **最大値(conservative)**: 安全側見積。値上がり・小ロット・端材率を見込む場合。")
    A("- **手入力(manual)**: 実際の引合・相見積がある場合は上書き必須。")
    A("- サンプル数が少ない(1〜2件)行はレンジが不安定。手入力推奨。")
    A("")
    _plate_range_tables(A, plate_rows, rate)
    _shape_range_tables(A, shape_rows)
    return "\n".join(L) + "\n"


def _plate_range_tables(A, plate_rows, rate):
    A("## 板厚別 価格レンジ（SS400, t1.6〜t32, 円/kg）")
    A("| 板厚 | plate_class | n | 中央(税抜) | 最大(税抜) | 中央(税込) | 最大(税込) |")
    A("|--:|---|--:|--:|--:|--:|--:|")
    prio = {pa.PLATE_RAW: 0, pa.PLATE_RECT: 1, pa.PLATE_SHAPED: 2}
    ss = [r for r in plate_rows if r["material_grade"] == "SS400"]
    ss.sort(key=lambda r: (_f(r["thickness_mm"]) or 0, prio.get(r["plate_class"], 9)))
    for r in ss:
        A(f"| t{r['thickness_mm']} | {r['plate_class']} | {r['sample_count']} | "
          f"{r['median_price_per_kg_ex_tax']} | {r['max_price_per_kg_ex_tax']} | "
          f"{r['median_price_per_kg_inc_tax']} | {r['max_price_per_kg_inc_tax']} |")
    miss = missing_thicknesses(plate_rows, "SS400")
    A("")
    A(f"### 欠けている板厚(SS400, t1.6〜t32): {', '.join('t'+str(t) for t in miss) or 'なし'}")
    A("（近傍板厚からの自動補間はしない。必要なら手入力で設定する。）")
    A("")


def _shape_range_tables(A, shape_rows):
    groups = [
        (C.SQUARE_PIPE, "角パイプ", "price_per_m"),
        (C.ROUND_PIPE, "丸パイプ", "price_per_m"),
        (C.FLAT_BAR, "FB", "price_per_m"),
        (C.ROUND_BAR, "丸棒", "price_per_kg"),
        (C.ANGLE, "アングル", "price_per_m"),
    ]
    for cat, label, metric in groups:
        rows = [r for r in shape_rows if r["material_category"] == cat][:12]
        if not rows:
            continue
        unit_label = "m単価" if metric == "price_per_m" else "kg単価"
        A(f"## {label} 価格レンジ（{unit_label}, 円, 税抜）")
        A(f"| 規格 | n | 本単価中央 | 本単価最大 | {unit_label}中央 | {unit_label}最大 |")
        A("|---|--:|--:|--:|--:|--:|")
        for r in rows:
            A(f"| {r['normalized_spec']} | {r['sample_count']} | "
              f"{r['median_unit_price_ex_tax']} | {r['max_unit_price_ex_tax']} | "
              f"{r['median_'+metric+'_ex_tax']} | {r['max_'+metric+'_ex_tax']} |")
        A("")


def write_report(path: str, text: str) -> None:
    import os
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
