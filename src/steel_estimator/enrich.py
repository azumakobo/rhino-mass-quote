"""layer_mapping の空欄を補完候補で埋める（Phase R6）。

設計の核心（既存方針の維持）:
  - 自動「確定」はしない。補完した項目には notes に
    `auto_enriched_review_required` を必ず残す。
  - 元 mapping / approved は上書きしない。結果は別ファイル
    （layer_mapping_enriched.csv）に保存する。
  - 既に値が入っている欄は触らない（補完は空欄のみ）。

補完ソース:
  1. レイヤー名のパース（layer_summary.suggest_for_layer）
  2. layer_summary.csv の suggested_*
  3. 実用単価マスター（toko_practical_price_master.csv）からの単価候補
"""

from __future__ import annotations

from . import csv_utils as cu
from . import candidate_prices as cp
from . import layer_mapping as lmap
from . import layer_summary as lsum
from . import price_suggestions as ps
from . import settings as tx


ENRICH_NOTE = "auto_enriched_review_required"

# 単価候補を採用してよい一致レベル（弱い一致でも候補としては残す）
_PRICE_LEVELS = ("exact", "exact_without_length", "dimension_match", "close",
                 "plate_reference_same_thickness", "plate_reference_near_thickness")


def _empty(v) -> bool:
    return v is None or str(v).strip() == ""


def _fmt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:g}"
    return str(v).strip()


def _pick(*vals):
    for v in vals:
        if not _empty(v):
            return v
    return None


def _master_to_pseudo_summary(master_rows: list[dict]) -> list[dict]:
    """practical master を price_suggestions が読めるサマリ形式に変換する。

    生材候補(usable_as_base_price=true)のみを生材照合に使う。plate_reference等の
    参考行は除外（別途フォールバックで扱う）。
    """
    pseudo = []
    for mm in master_rows:
        if mm.get("candidate_class") == "plate_reference":
            continue
        d = dict(mm)
        # 明示の usable_as_base_price 列があれば尊重、無ければ usability から導出
        if not d.get("usable_as_base_price"):
            d["usable_as_base_price"] = (
                "true" if mm.get("usability") in ("ready", "usable_with_review") else "false"
            )
        pseudo.append(d)
    return pseudo


def _plate_refs_from_master(master_rows: list[dict]) -> list[dict]:
    """master内の plate_reference 行を、板材フォールバック照合用の形に整える。"""
    out = []
    for r in master_rows:
        if r.get("candidate_class") != "plate_reference":
            continue
        parts = (r.get("spec_key", "") or "").split("|")  # plate_ref|grade|tX|class
        thick = parts[2][1:] if len(parts) > 2 and parts[2].startswith("t") else ""
        pclass = parts[3] if len(parts) > 3 else ""
        out.append({
            "material_grade": r.get("material_grade", ""),
            "thickness_mm": thick,
            "plate_class": pclass,
            "median_price_per_kg": r.get("price_per_kg", ""),
            "latest_quote_date": r.get("latest_quote_date", ""),
            "confidence": r.get("confidence", 0.4),
            "usable_as_reference": r.get("usable_as_reference", "true"),
        })
    return out


_SHAPE_CATS = ("square_pipe", "round_pipe", "flat_bar", "round_bar",
               "angle", "square_bar", "h_beam", "channel")
_PLATE_PRIO = {"raw_plate": 0, "rectangular_cut_plate": 1, "shaped_cut_plate": 2}


def _match_shape_range(row: dict, shape_range: list[dict]):
    """mapping行の指定寸法に一致する steel_shape_price_range_master 行を返す。"""
    cat = row.get("material_category", "")
    cands = [r for r in shape_range if r.get("material_category") == cat]
    md = {k: cu.to_float(row.get(k)) for k in ("width_mm", "height_mm", "thickness_mm", "diameter_mm")}
    best, best_score = None, -1
    for r in cands:
        score = 0
        ok = True
        for k in ("width_mm", "height_mm", "thickness_mm", "diameter_mm"):
            mv, rv = md.get(k), cu.to_float(r.get(k))
            if mv is not None and rv is not None:
                if abs(mv - rv) <= 0.01:
                    score += 1
                else:
                    ok = False
                    break
        if ok and score > best_score:
            best, best_score = r, score
    return best if best_score >= 1 else None


def _apply_range_masters(row, plate_range, shape_range):
    """recommended/conservative 単価とpricing_modeを設定する。戻り: (enriched_fields, price_unit)。"""
    cat = row.get("material_category", "")
    rec = con = None
    src = ""
    unit = row.get("price_unit", "")
    if cat == "plate" and plate_range:
        t = cu.to_float(row.get("thickness_mm"))
        grade = (row.get("material_grade", "") or "").upper()
        cands = [r for r in plate_range
                 if t is not None and cu.to_float(r.get("thickness_mm")) == t]
        if cands:
            cands.sort(key=lambda r: (
                0 if (grade and r.get("material_grade", "").upper() == grade) else 1,
                _PLATE_PRIO.get(r.get("plate_class", ""), 9)))
            b = cands[0]
            rec = cu.to_float(b.get("recommended_price_per_kg_ex_tax"))
            con = cu.to_float(b.get("conservative_price_per_kg_ex_tax"))
            unit = unit or "kg"
            src = f"plate_range:{b.get('material_grade')}|t{b.get('thickness_mm')}|{b.get('plate_class')}"
    elif cat in _SHAPE_CATS and shape_range:
        b = _match_shape_range(row, shape_range)
        if b:
            metric = "price_per_m" if unit == "m" else ("price_per_kg" if unit == "kg" else "unit_price")
            rec = cu.to_float(b.get(f"recommended_{metric}_ex_tax"))
            con = cu.to_float(b.get(f"conservative_{metric}_ex_tax"))
            src = f"shape_range:{b.get('spec_key')}"
    if rec is None:
        return [], unit, src
    fields = []
    if _empty(row.get("recommended_unit_price")):
        row["recommended_unit_price"] = _fmt(rec); fields.append("recommended_unit_price")
    if con is not None and _empty(row.get("conservative_unit_price")):
        row["conservative_unit_price"] = _fmt(con); fields.append("conservative_unit_price")
    if _empty(row.get("price_range_source")):
        row["price_range_source"] = src; fields.append("price_range_source")
    if _empty(row.get("pricing_mode")):
        # ユーザーがunit_priceを明示済みなら manual を尊重、なければ median を初期値
        row["pricing_mode"] = "manual" if not _empty(row.get("unit_price")) else "median"
        fields.append("pricing_mode")
    if _empty(row.get("selected_unit_price")):
        row["selected_unit_price"] = _fmt(rec) if row["pricing_mode"] == "median" else row.get("unit_price", "")
        fields.append("selected_unit_price")
    if _empty(row.get("unit_price")) and row["pricing_mode"] == "median":
        row["unit_price"] = _fmt(rec); fields.append("unit_price")
    if _empty(row.get("price_unit")) and unit:
        row["price_unit"] = unit; fields.append("price_unit")
    return fields, unit, src


def enrich_mapping(mapping_rows: list[dict], summary_rows: list[dict],
                   master_rows: list[dict],
                   tax_rate: float = tx.DEFAULT_TAX_RATE,
                   plate_range_rows: list[dict] | None = None,
                   shape_range_rows: list[dict] | None = None) -> list[dict]:
    """補完済み mapping 行を新規リストで返す（入力は破壊しない）。

    mapping の unit_price は税抜のまま埋める（二重課税防止）。税込は notes に参考表示。
    価格レンジマスターが渡されれば recommended/conservative と pricing_mode を設定する。
    """
    rate = tx.normalize_rate(tax_rate)
    summ_idx = {s.get("layer_name", ""): s for s in summary_rows}
    pseudo = _master_to_pseudo_summary(master_rows)
    plate_refs = _plate_refs_from_master(master_rows)

    out = []
    for m in mapping_rows:
        row = {f: m.get(f, "") for f in lmap.MAPPING_FIELDS}
        name = row.get("layer_name", "")
        enriched: list[str] = []

        def fill(field, value):
            if _empty(value):
                return
            if _empty(row.get(field)):
                row[field] = _fmt(value)
                enriched.append(field)

        guess = lsum.suggest_for_layer(name)
        s = summ_idx.get(name, {})

        # --- 1) レイヤー名 / summary から寸法・カテゴリを補完 ---
        fill("material_category",
             _pick(guess.get("suggested_material_category"),
                   s.get("suggested_material_category")))
        fill("calc_type",
             _pick(guess.get("suggested_calc_type"), s.get("suggested_calc_type")))
        fill("spec_text", _pick(s.get("suggested_spec_text"), name))
        fill("thickness_mm",
             _pick(guess.get("suggested_thickness_mm"), s.get("suggested_thickness_mm")))
        fill("diameter_mm",
             _pick(guess.get("suggested_diameter_mm"), s.get("suggested_diameter_mm")))
        fill("width_mm",
             _pick(guess.get("suggested_width_mm"), s.get("suggested_width_mm")))
        fill("height_mm",
             _pick(guess.get("suggested_height_mm"), s.get("suggested_height_mm")))

        # --- 2) 価格レンジマスター優先（中央値=median を初期 unit_price に・pricing_mode=median） ---
        range_filled = False
        if plate_range_rows or shape_range_rows:
            rfields, _ru, _rsrc = _apply_range_masters(row, plate_range_rows, shape_range_rows)
            if rfields:
                enriched.extend(rfields)
                range_filled = True

        # --- 2b) レンジ未マッチ時のみ、実用単価マスター候補で unit_price を補完 ---
        sug = ps.suggest_for_mapping([row], pseudo, plate_reference_rows=plate_refs)[0]
        level = sug.get("match_level", "none")
        price_filled = False
        if level in _PRICE_LEVELS and sug.get("suggested_unit_price"):
            parsed = cp.parse_spec_key(sug.get("suggested_spec_key", ""))
            fill("material_grade", parsed.get("grade"))
            fill("stock_length_mm", parsed.get("length"))
            if _empty(row.get("price_unit")):
                fill("price_unit", sug.get("suggested_price_unit"))
            if _empty(row.get("unit_price")):
                row["unit_price"] = _fmt(sug.get("suggested_unit_price"))
                enriched.append("unit_price")
                price_filled = True
                if _empty(row.get("price_source")):
                    row["price_source"] = (
                        f"auto:practical_master({level}) "
                        f"{sug.get('suggested_vendor', '')} "
                        f"{sug.get('suggested_quote_date', '')}".strip()
                    )

        # --- 3) notes に補完痕跡を残す（確定でないことを明記） ---
        if range_filled:
            row["notes"] = (f"{row.get('notes','')}; 価格レンジ候補。手入力変更可。"
                            ).strip("; ")
        if enriched:
            tags = ENRICH_NOTE + ":" + ",".join(sorted(set(enriched)))
            if price_filled:
                # unit_price は税抜のまま。税込は参考として notes に併記（二重課税防止）。
                inc = tx.inc_of(row["unit_price"], rate)
                unit = row.get("price_unit", "") or ""
                tags += (f"; unit_price自動補完(税抜・要確認・未承認); "
                         f"税込参考: {inc}円/{unit}(tax {rate:.0%})")
            base = row.get("notes", "")
            row["notes"] = f"{base}; {tags}".strip("; ") if base else tags
        out.append(row)
    return out


def write_enriched(path: str, rows: list[dict]) -> int:
    return lmap.write_mapping(path, rows)


def enriched_field_count(original_rows: list[dict], enriched_rows: list[dict]) -> int:
    """補完で新たに値が入ったセル数を数える（レポート用）。"""
    idx = {r.get("layer_name", ""): r for r in original_rows}
    count = 0
    for er in enriched_rows:
        orig = idx.get(er.get("layer_name", ""), {})
        for f in lmap.MAPPING_FIELDS:
            if f == "notes":
                continue
            if _empty(orig.get(f)) and not _empty(er.get(f)):
                count += 1
    return count
