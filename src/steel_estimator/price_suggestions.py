"""layer_mapping の各レイヤーに、候補単価サマリから単価を提案する。

重要: 提案は別CSVに出すだけ。layer_mapping.csv へは自動反映しない（人間が確認して反映）。
"""

from __future__ import annotations

from . import csv_utils as cu
from . import layer_mapping as lmap
from . import candidate_prices as cp
from .models import MaterialCategory as C


SUGGESTION_FIELDS = (
    "layer_name", "calc_type", "material_category", "material_grade", "spec_text",
    "current_unit_price", "suggested_unit_price", "suggested_price_unit",
    "suggested_vendor", "suggested_quote_date", "suggested_spec_key",
    "match_level", "confidence", "needs_review", "warning", "notes",
)

# カテゴリ別の比較対象寸法
_CMP_DIMS = {
    C.ROUND_PIPE: ("diameter", "thickness"),
    C.ROLLED: ("diameter", "thickness"),
    C.ROUND_BAR: ("diameter",),
    C.SQUARE_PIPE: ("width", "height", "thickness"),
    C.ANGLE: ("width", "height", "thickness"),
    C.CHANNEL: ("width", "height", "thickness"),
    C.H_BEAM: ("width", "height", "thickness"),
    C.FLAT_BAR: ("thickness", "width"),
    C.PLATE: ("thickness",),
}


def _mapping_dims(m: dict) -> dict:
    return {
        "diameter": cu.to_float(m.get("diameter_mm")),
        "thickness": cu.to_float(m.get("thickness_mm")),
        "width": cu.to_float(m.get("width_mm")),
        "height": cu.to_float(m.get("height_mm")),
    }


def _mapping_length(m: dict):
    return cu.to_float(m.get("stock_length_mm"))


def _approx(a, b, tol):
    if a is None or b is None:
        return False
    if b == 0:
        return a == 0
    return abs(a - b) / abs(b) <= tol


def _score_candidate(m: dict, mdims: dict, cand_parsed: dict, grade: str,
                     mlen=None) -> str:
    """1候補との一致レベルを返す。

    exact               : 材質一致＋断面寸法フル一致（長さは比較対象外/一致）
    exact_without_length: 材質一致＋断面フル一致だが、両側に長さがあり長さのみ不一致
    dimension_match     : 材質未指定 or 一部寸法のみだが、既知の断面寸法が厳密一致
    close               : 既知寸法が近似（15%以内）
    category_only       : カテゴリのみ一致
    """
    keys = _CMP_DIMS.get(m.get("material_category", ""), ())
    cgrade = cand_parsed.get("grade", "") or ""
    grade_both = bool(grade) and bool(cgrade) and grade.upper() == cgrade.upper()
    grade_conflict = bool(grade) and bool(cgrade) and grade.upper() != cgrade.upper()

    comparable = [k for k in keys if mdims.get(k) is not None and cand_parsed.get(k) is not None]
    if not (keys and comparable):
        return "category_only"

    exact_dims = all(_approx(mdims[k], cand_parsed[k], 0.001) for k in comparable)
    close_dims = all(_approx(mdims[k], cand_parsed[k], 0.15) for k in comparable)
    full = len(comparable) == len(keys)
    clen = cand_parsed.get("length")

    if exact_dims and not grade_conflict:
        if full and grade_both:
            # 断面・材質ともフル一致。長さが両側にあり食い違うときだけ格下げ
            if mlen is not None and clen is not None and not _approx(mlen, clen, 0.001):
                return "exact_without_length"
            return "exact"
        # 材質未指定、または一部寸法のみ既知だが厳密一致
        return "dimension_match"
    if close_dims:
        return "close"
    return "category_only"


_LEVEL_RANK = {
    "exact": 6, "exact_without_length": 5, "dimension_match": 4,
    "close": 3, "category_only": 2, "none": 0,
}


def suggest_for_mapping(mapping_rows: list[dict], summary_rows: list[dict],
                        plate_reference_rows: list[dict] | None = None) -> list[dict]:
    # 生材として使える候補のみ提案対象（加工品・JIS要マスターは除外）
    usable = [s for s in summary_rows if s.get("usable_as_base_price") == "true"]
    by_cat: dict[str, list[dict]] = {}
    for s in usable:
        by_cat.setdefault(s.get("material_category", ""), []).append(s)

    out = []
    for m in mapping_rows:
        cat = m.get("material_category", "")
        grade = m.get("material_grade", "")
        mdims = _mapping_dims(m)
        mlen = _mapping_length(m)
        current_price = m.get("unit_price", "")

        best = None
        best_level = "none"
        for s in by_cat.get(cat, []):
            parsed = cp.parse_spec_key(s.get("spec_key", ""))
            level = _score_candidate(m, mdims, parsed, grade, mlen)
            if _LEVEL_RANK[level] > _LEVEL_RANK[best_level] or (
                level == best_level and best is not None
                and (s.get("latest_quote_date") or "") > (best.get("latest_quote_date") or "")
            ):
                best, best_level = s, level

        sug = _make_suggestion(m, current_price, best, best_level)

        # 板材で生板(raw_plate)候補が弱い場合、型切/切板由来の参考単価をフォールバック提示
        if (cat == C.PLATE and plate_reference_rows
                and best_level in ("none", "category_only")):
            pr, pr_level = _match_plate_reference(m, plate_reference_rows)
            if pr is not None:
                sug = _make_plate_ref_suggestion(m, current_price, pr, pr_level)
        out.append(sug)
    return out


# 型切/切板由来の参考単価に必ず付ける警告
PLATE_REF_WARNING = "型切/切板由来の外接矩形ベース参考単価。生板単価ではないため要確認。"
_PLATE_CLASS_PRIO = {
    "raw_plate": 0, "rectangular_cut_plate": 1, "shaped_cut_plate": 2,
    "bent_plate": 3, "unknown_plate": 4,
}


def _match_plate_reference(m: dict, refs: list[dict]):
    """板材mappingに対し板厚別参考単価を照合する。

    優先: raw>rectangular>shaped、材質一致を優先、同板厚>近似板厚(±25%)。
    戻り: (参考行 or None, match_level)。
    """
    mt = cu.to_float(m.get("thickness_mm"))
    mgrade = (m.get("material_grade", "") or "").upper()
    usable = [r for r in refs
              if r.get("usable_as_reference") == "true" and r.get("median_price_per_kg")]
    if mt is None or not usable:
        return None, None

    def sort_key(r):
        rgrade = (r.get("material_grade", "") or "").upper()
        grade_match = 0 if (mgrade and rgrade == mgrade) else 1
        prio = _PLATE_CLASS_PRIO.get(r.get("plate_class", ""), 9)
        return (grade_match, prio, -(_date_num(r.get("latest_quote_date"))))

    same = [r for r in usable if _approx(mt, cu.to_float(r.get("thickness_mm")), 0.001)]
    if same:
        return sorted(same, key=sort_key)[0], "plate_reference_same_thickness"
    near = [r for r in usable if _approx(mt, cu.to_float(r.get("thickness_mm")), 0.25)]
    if near:
        return sorted(near, key=sort_key)[0], "plate_reference_near_thickness"
    return None, None


def _date_num(s) -> int:
    s = (s or "").replace("-", "")
    return int(s) if s.isdigit() else 0


def _make_plate_ref_suggestion(m, current_price, pr, level) -> dict:
    note = ("同板厚の参考単価" if level == "plate_reference_same_thickness"
            else "近似板厚の参考単価")
    return {
        "layer_name": m.get("layer_name", ""),
        "calc_type": m.get("calc_type", ""),
        "material_category": m.get("material_category", ""),
        "material_grade": m.get("material_grade", ""),
        "spec_text": m.get("spec_text", ""),
        "current_unit_price": current_price,
        "suggested_unit_price": pr.get("median_price_per_kg", ""),
        "suggested_price_unit": "kg",
        "suggested_vendor": "東鋼材",
        "suggested_quote_date": pr.get("latest_quote_date", ""),
        "suggested_spec_key": f"plate_ref|{pr.get('material_grade', '')}|"
                              f"t{pr.get('thickness_mm', '')}|{pr.get('plate_class', '')}",
        "match_level": level,
        "confidence": pr.get("confidence", 0.4),
        "needs_review": "true",
        "warning": f"{PLATE_REF_WARNING} ({note}, {pr.get('plate_class', '')})",
        "notes": "型切/切板由来の参考。生板単価ではない。layer_mappingへは人間が反映する。",
    }


def _make_suggestion(m, current_price, best, level) -> dict:
    row = {
        "layer_name": m.get("layer_name", ""),
        "calc_type": m.get("calc_type", ""),
        "material_category": m.get("material_category", ""),
        "material_grade": m.get("material_grade", ""),
        "spec_text": m.get("spec_text", ""),
        "current_unit_price": current_price,
        "suggested_unit_price": "",
        "suggested_price_unit": "",
        "suggested_vendor": "",
        "suggested_quote_date": "",
        "suggested_spec_key": "",
        "match_level": level,
        "confidence": "",
        "needs_review": "true",
        "warning": "",
        "notes": "提案のみ。layer_mappingへは人間が反映する。",
    }
    if best is None or level == "none":
        row["match_level"] = "none"
        row["warning"] = "該当する生材候補なし"
        return row

    row["suggested_unit_price"] = best.get("latest_unit_price", "")
    row["suggested_price_unit"] = best.get("price_unit", "")
    row["suggested_vendor"] = best.get("vendor_name", "")
    row["suggested_quote_date"] = best.get("latest_quote_date", "")
    row["suggested_spec_key"] = best.get("spec_key", "")
    row["confidence"] = best.get("confidence", "")
    warn = []
    if best.get("warning"):
        warn.append(best["warning"])
    _LEVEL_NOTE = {
        "exact_without_length": "断面・材質は一致、長さのみ不一致/未指定（定尺材として有用、長さ要確認）",
        "dimension_match": "断面寸法は一致だが材質または一部寸法が未確定",
        "close": "寸法が近似（完全一致でない）",
        "category_only": "カテゴリのみ一致（寸法根拠が弱い）",
    }
    if level in _LEVEL_NOTE:
        warn.append(f"一致レベル={level}: {_LEVEL_NOTE[level]}")
    row["warning"] = "; ".join(warn)
    # exact かつ候補にwarningが無ければ review 不要寄りだが、最終確認は人間
    row["needs_review"] = "false" if (level == "exact" and not best.get("warning")) else "true"
    return row


def match_level_counts(suggestion_rows: list[dict]) -> dict:
    counts = {"exact": 0, "exact_without_length": 0, "dimension_match": 0,
              "close": 0, "category_only": 0,
              "plate_reference_same_thickness": 0,
              "plate_reference_near_thickness": 0, "none": 0}
    for r in suggestion_rows:
        lvl = r.get("match_level", "none")
        counts[lvl] = counts.get(lvl, 0) + 1
    return counts


# ============================================================
# 照合失敗分析（match_failure_analysis）
# ============================================================

MATCH_FAILURE_FIELDS = (
    "layer_name", "material_category", "spec_text", "current_match_level",
    "reason_no_exact", "missing_fields", "candidate_count_same_category",
    "candidate_count_same_dimension", "recommended_mapping_fix",
    "recommended_user_action",
)


def build_match_failure_analysis(mapping_rows: list[dict],
                                 summary_rows: list[dict]) -> list[dict]:
    """各レイヤーが exact にならない原因を分析する。"""
    suggestions = suggest_for_mapping(mapping_rows, summary_rows)
    sug_by_layer = {s["layer_name"]: s for s in suggestions}
    usable = [s for s in summary_rows if s.get("usable_as_base_price") == "true"]
    by_cat: dict[str, list[dict]] = {}
    for s in usable:
        by_cat.setdefault(s.get("material_category", ""), []).append(s)

    out = []
    for m in mapping_rows:
        cat = m.get("material_category", "") or ""
        grade = m.get("material_grade", "") or ""
        mdims = _mapping_dims(m)
        level = sug_by_layer.get(m.get("layer_name", ""), {}).get("match_level", "none")

        keys = _CMP_DIMS.get(cat, ())
        missing = []
        if not cat:
            missing.append("material_category")
        if not grade:
            missing.append("material_grade")
        for k in keys:
            if mdims.get(k) is None:
                missing.append(f"{k}_mm")

        same_cat = by_cat.get(cat, [])
        same_dim = 0
        for s in same_cat:
            parsed = cp.parse_spec_key(s.get("spec_key", ""))
            comparable = [k for k in keys
                          if mdims.get(k) is not None and parsed.get(k) is not None]
            if comparable and all(_approx(mdims[k], parsed[k], 0.001) for k in comparable):
                same_dim += 1

        out.append({
            "layer_name": m.get("layer_name", ""),
            "material_category": cat,
            "spec_text": m.get("spec_text", ""),
            "current_match_level": level,
            "reason_no_exact": _reason_no_exact(level, cat, grade, missing, len(same_cat)),
            "missing_fields": ", ".join(missing),
            "candidate_count_same_category": len(same_cat),
            "candidate_count_same_dimension": same_dim,
            "recommended_mapping_fix": _recommended_fix(level, missing, cat),
            "recommended_user_action": _recommended_action(level, len(same_cat)),
        })
    return out


def _reason_no_exact(level, cat, grade, missing, cand_count) -> str:
    if level == "exact":
        return "exact一致（問題なし）"
    if not cat:
        return "material_category未設定のため候補と照合不可"
    if cand_count == 0:
        return f"カテゴリ{cat}に生材候補が0件"
    parts = []
    if "material_grade" in missing:
        parts.append("material_grade未入力（STKR/STK400等の規格未指定）")
    dim_missing = [x for x in missing if x.endswith("_mm")]
    if dim_missing:
        parts.append("断面寸法不足: " + ", ".join(dim_missing))
    if level == "exact_without_length":
        parts.append("定尺長(stock_length_mm)が候補と不一致/未指定")
    if not parts:
        parts.append("寸法が候補と近似のみ（厳密一致せず）")
    return "; ".join(parts)


def _recommended_fix(level, missing, cat) -> str:
    if level == "exact":
        return "なし"
    if "material_category" in missing:
        return "material_category を設定（round_pipe/square_pipe/plate等）"
    fixes = []
    if "material_grade" in missing:
        fixes.append("material_grade を入力")
    dim_missing = [x for x in missing if x.endswith("_mm")]
    if dim_missing:
        fixes.append(" / ".join(dim_missing) + " を入力")
    if level == "exact_without_length":
        fixes.append("stock_length_mm を定尺(例6000)に設定")
    return "; ".join(fixes) or "spec_text から寸法を補完"


def _recommended_action(level, cand_count) -> str:
    if level == "exact":
        return "そのまま採用可（最終確認）"
    if cand_count == 0:
        return "別業者の単価入力、または手動単価設定"
    if level in ("exact_without_length", "dimension_match"):
        return "提案単価を確認のうえ採用（断面一致・要レビュー）"
    return "layer_mappingに材質・寸法を補完して再実行"


def write_match_failure_analysis(path: str, rows: list[dict]) -> int:
    return cu.write_dicts(path, MATCH_FAILURE_FIELDS, rows)


def read_summary(path: str) -> list[dict]:
    return cu.read_dicts(path)


def write_suggestions(path: str, rows: list[dict]) -> int:
    return cu.write_dicts(path, SUGGESTION_FIELDS, rows)
