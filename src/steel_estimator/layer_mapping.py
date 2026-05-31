"""layer_mapping.csv の読み書きと雛形生成・更新。

設計の核心: レイヤー名の自動パースは「正解」ではなく、人間が編集する
layer_mapping.csv を計算の正とする。雛形には summary の suggested_* を初期値として
入れるだけで、確定値ではない。
"""

from __future__ import annotations

from typing import Optional

from . import csv_utils as cu


# calc_type 一覧
CALC_AREA_TO_WEIGHT = "area_to_weight"
CALC_VOLUME_TO_WEIGHT = "volume_to_weight"
CALC_CURVE_TO_STOCK = "curve_length_to_stock"
CALC_CURVE_TO_METER = "curve_length_to_meter"
CALC_OBJECT_COUNT = "object_count"
CALC_MANUAL_QTY = "manual_quantity"
CALC_FIXED_AMOUNT = "fixed_amount"
CALC_IGNORE = "ignore"

CALC_TYPES = (
    CALC_AREA_TO_WEIGHT, CALC_VOLUME_TO_WEIGHT, CALC_CURVE_TO_STOCK,
    CALC_CURVE_TO_METER, CALC_OBJECT_COUNT, CALC_MANUAL_QTY,
    CALC_FIXED_AMOUNT, CALC_IGNORE,
)

# 各 calc_type が期待する price_unit（矛盾検出用）。None は不問。
EXPECTED_PRICE_UNIT = {
    CALC_AREA_TO_WEIGHT: {"kg"},
    CALC_VOLUME_TO_WEIGHT: {"kg"},
    CALC_CURVE_TO_STOCK: {"stock", "本"},      # "6m" 等の N m 表記も別途許可
    CALC_CURVE_TO_METER: {"m", "メートル"},
    CALC_OBJECT_COUNT: {"個", "piece", "pcs", "本", "ea"},
    CALC_MANUAL_QTY: None,
    CALC_FIXED_AMOUNT: None,
    CALC_IGNORE: None,
}

MAPPING_FIELDS = (
    "layer_name",
    "enabled",
    "calc_type",
    "material_category",
    "material_grade",
    "spec_text",
    "thickness_mm",
    "diameter_mm",
    "width_mm",
    "height_mm",
    "stock_length_mm",
    "density_g_cm3",
    "unit_price",
    "price_unit",
    "waste_rate",
    "quantity_override",
    "fixed_amount",
    "price_source",
    # --- 価格レンジ/手入力（R6.3）。unit_price は税抜で互換維持。 ---
    "pricing_mode",
    "manual_unit_price",
    "recommended_unit_price",
    "conservative_unit_price",
    "selected_unit_price",
    "selected_price_basis",
    "price_range_source",
    "notes",
)

# pricing_mode の選択肢
PRICING_MODES = ("manual", "median", "conservative", "latest", "average")


def resolve_pricing(m: dict) -> Optional[dict]:
    """layer_mapping行の pricing_mode から採用単価を決める。

    戻り: {selected, basis, mode, recommended, conservative} または None（レンジ情報なし）。
    None のときは従来の単価解決ロジックをそのまま使う（互換維持）。
    unit_price は税抜のまま扱い、税込変換はしない（二重課税防止）。
    """
    mode = (m.get("pricing_mode", "") or "").strip().lower()
    manual = cu.to_float(m.get("manual_unit_price"))
    up = cu.to_float(m.get("unit_price"))
    rec = cu.to_float(m.get("recommended_unit_price"))
    con = cu.to_float(m.get("conservative_unit_price"))

    # pricing系もmanualもレンジも空 → 従来フロー
    if not mode and manual is None and rec is None and con is None:
        return None

    if not mode:
        # ユーザーが unit_price を明示していて recommended が無ければ manual 優先
        mode = "manual" if (up is not None and rec is None) else "median"

    if mode == "manual":
        sel, basis = (manual if manual is not None else up), "manual"
    elif mode == "conservative":
        sel, basis = (con if con is not None else up), "conservative(max)"
    elif mode == "latest":
        sel = cu.to_float(m.get("latest_unit_price")) or up or rec
        basis = "latest"
    elif mode == "average":
        sel = cu.to_float(m.get("average_unit_price")) or rec or up
        basis = "average"
    else:  # median / recommended
        mode = "median"
        sel, basis = (rec if rec is not None else up), "median"

    recommended = rec if rec is not None else sel
    conservative = con if con is not None else sel
    return {"selected": sel, "basis": basis, "mode": mode,
            "recommended": recommended, "conservative": conservative}


def read_mapping(path: str) -> list[dict]:
    """layer_mapping.csv を生 dict のリストで読む（値は文字列のまま保持）。"""
    rows = cu.read_dicts(path)
    # MAPPING_FIELDS を必ず備えるよう欠損キーを補完
    for r in rows:
        for f in MAPPING_FIELDS:
            r.setdefault(f, "")
    return rows


def mapping_index(rows: list[dict]) -> dict:
    """layer_name → mapping行 の辞書。日本語・記号キーをそのまま使う。"""
    return {r.get("layer_name", ""): r for r in rows}


def _seed_row_from_summary(s: dict) -> dict:
    """summary 1行から mapping 雛形1行を作る。suggested_* を初期値に流用。"""
    suggested_price_unit = _default_price_unit(s.get("suggested_calc_type", ""))
    return {
        "layer_name": s.get("layer_name", ""),
        "enabled": "true",
        "calc_type": s.get("suggested_calc_type", ""),
        "material_category": s.get("suggested_material_category", ""),
        "material_grade": "",
        "spec_text": s.get("suggested_spec_text", ""),
        "thickness_mm": s.get("suggested_thickness_mm", ""),
        "diameter_mm": s.get("suggested_diameter_mm", ""),
        "width_mm": s.get("suggested_width_mm", ""),
        "height_mm": s.get("suggested_height_mm", ""),
        "stock_length_mm": "",
        "density_g_cm3": "",
        "unit_price": "",
        "price_unit": suggested_price_unit,
        "waste_rate": "1.0",
        "quantity_override": "",
        "fixed_amount": "",
        "price_source": "",
        "pricing_mode": "",
        "manual_unit_price": "",
        "recommended_unit_price": "",
        "conservative_unit_price": "",
        "selected_unit_price": "",
        "selected_price_basis": "",
        "price_range_source": "",
        # 自動推定は確定でないことを明記
        "notes": "自動推定値。確認・修正してください。" + (
            (" " + s.get("warning", "")) if s.get("warning") else ""
        ),
    }


def _default_price_unit(calc_type: str) -> str:
    return {
        CALC_AREA_TO_WEIGHT: "kg",
        CALC_VOLUME_TO_WEIGHT: "kg",
        CALC_CURVE_TO_STOCK: "stock",
        CALC_CURVE_TO_METER: "m",
        CALC_OBJECT_COUNT: "個",
    }.get(calc_type, "")


def init_mapping_from_summary(summary_rows: list[dict]) -> list[dict]:
    """layer_summary 全行から mapping 雛形を生成（全レイヤー分）。"""
    return [_seed_row_from_summary(s) for s in summary_rows]


def update_mapping(existing_rows: list[dict], summary_rows: list[dict]) -> tuple[list[dict], list[str]]:
    """既存 mapping を壊さず、summary にしか無い新規レイヤーだけ追記する。

    戻り: (更新後の全行, 追加されたlayer_nameのリスト)
    既存行はそのまま（順序・値とも保持）。
    """
    existing = [dict(r) for r in existing_rows]
    have = {r.get("layer_name", "") for r in existing}
    added = []
    for s in summary_rows:
        name = s.get("layer_name", "")
        if name and name not in have:
            existing.append(_seed_row_from_summary(s))
            have.add(name)
            added.append(name)
    return existing, added


def write_mapping(path: str, rows: list[dict]) -> int:
    return cu.write_dicts(path, MAPPING_FIELDS, rows)
