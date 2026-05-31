"""rhino_objects から layer_summary を作る集計層と、レイヤー名の自動推定。

重要: ここで返す suggested_* はあくまで初期値の候補であり、確定値ではない。
最終的な計算は人間が編集する layer_mapping.csv を正とする（設計書 §9）。
"""

from __future__ import annotations

import re
from collections import OrderedDict
from typing import Optional

from . import csv_utils as cu
from . import material_parser as mp
from .models import MaterialCategory as C


LAYER_SUMMARY_FIELDS = (
    "layer_name",
    "object_count",
    "total_area_m2",
    "total_volume_mm3",
    "total_curve_length_m",
    "detected_object_types",
    "bounding_box_note",
    "suggested_calc_type",
    "suggested_material_category",
    "suggested_spec_text",
    "suggested_thickness_mm",
    "suggested_diameter_mm",
    "suggested_width_mm",
    "suggested_height_mm",
    "needs_mapping",
    "warning",
    "notes",
)

# calc_type 文字列（layer_mapping への依存を避けるためリテラルで保持）
_AREA = "area_to_weight"
_VOLUME = "volume_to_weight"
_STOCK = "curve_length_to_stock"
_METER = "curve_length_to_meter"
_COUNT = "object_count"
_FIXED = "fixed_amount"
_IGNORE = "ignore"

# 名前ヒント（部分一致）
IGNORE_HINTS = ("補助線", "補助", "注釈", "検討", "ガイド", "参考", "寸法線", "通り芯",
                "guide", "reference", "axis", "annotation", "dim")
COST_HINTS = ("塗装", "運搬", "加工", "曲げ", "溶接", "切断", "穴あけ", "設計",
              "施工", "取付", "外注", "費")
COUNT_HINTS = ("ボルト", "ナット", "ビス", "金物", "キャスター", "ベアリング", "車輪",
               "購入部品", "ヒンジ", "蝶番", "アンカー")
PLATE_HINTS = ("鉄板", "鋼板", "縞板", "縞鋼板", "プレート", "板金", "板", "plate", "PL")
LINEAR_HINTS = ("角パイプ", "丸パイプ", "パイプ", "アングル", "チャンネル", "Cチャン",
                "フラットバー", "平鋼", "FB", "手すり", "手摺", "H形鋼", "丸棒", "角棒")

THICK_RE = re.compile(r"(?:板厚|厚|t)?\s?(\d+(?:\.\d+)?)\s?mm", re.IGNORECASE)
THICK_T_RE = re.compile(r"(?:^|[^A-Za-z])t\s?(\d+(?:\.\d+)?)", re.IGNORECASE)
PHI_RE = mp.PHI_RE
PAIR_RE = re.compile(r"(\d+(?:\.\d+)?)\s?[x×X*]\s?(\d+(?:\.\d+)?)")
NUM_RE = re.compile(r"\d+(?:\.\d+)?")
# 'D48.6' のような径表記（境界の直後の D + 数値）。SD295A 等の途中Dは拾わない。
DIA_D_RE = re.compile(r"(?:^|[_\s\-])D(\d+(?:\.\d+)?)")

# 公開デモ等で使う ASCII レイヤー命名コード（先頭トークンで判定）。
# 例: PL_SS400_t6 / SQPIPE_STKR_100x50_t2.3 / PIPE_STK400_D101.6_t3.2 /
#     FB_SS400_50x4.5 / ANGLE_SS400_40x40_t3 / BOLT_TEST / IGNORE_GUIDE
ASCII_CODE_CAT = {
    "PL": "plate", "PLATE": "plate",
    "SQPIPE": "square_pipe", "SQ": "square_pipe",
    "PIPE": "round_pipe", "RPIPE": "round_pipe",
    "ANGLE": "angle",
    "FB": "flat_bar",
    "CH": "channel", "CHANNEL": "channel",
    "RBAR": "round_bar", "SBAR": "square_bar", "HBEAM": "h_beam",
}
ASCII_CODE_SPECIAL = {"BOLT": "object_count", "NUT": "object_count",
                      "SCREW": "object_count", "IGNORE": "ignore", "GUIDE": "ignore"}

# 鋼材系カテゴリ: ポリサーフェス体積から重量で見積もる（標準方針 / 体積>0 なら volume_to_weight）。
STEEL_VOLUME_CATEGORIES = (
    "square_pipe", "round_pipe", "angle", "flat_bar",
    "round_bar", "square_bar", "h_beam", "channel",
)
# 種別名から鋼材汎用と判断するコード/語（category空でも体積重量にする）
STEEL_NAME_CODES = ("STEEL", "METAL", "STEELPART", "METALPART", "STEEL_PART", "METAL_PART")


def is_steel_volume_layer(name: str, category: str) -> bool:
    """鋼材系（ポリサーフェス体積重量の対象）か。"""
    if category in STEEL_VOLUME_CATEGORIES:
        return True
    code = _ascii_code(name)
    n = (name or "").upper().replace("_", "")
    return code in STEEL_NAME_CODES or any(c.replace("_", "") in n for c in STEEL_NAME_CODES)


def _ascii_code(name: str) -> str:
    """レイヤー名の先頭 '_' 区切りトークンを大文字で返す（ASCII命名コード判定用）。"""
    if not name:
        return ""
    first = name.split("_", 1)[0] if "_" in name else name
    return first.strip().upper()


# ============================================================
# 自動推定（候補のみ）
# ============================================================

def suggest_dimensions(name: str) -> dict:
    """レイヤー名から寸法候補を抽出（確定値ではない）。"""
    out = {"thickness_mm": None, "diameter_mm": None, "width_mm": None, "height_mm": None}
    if not name:
        return out
    phi = PHI_RE.search(name)
    if phi:
        out["diameter_mm"] = float(phi.group(1))
    if out["diameter_mm"] is None:
        dm = DIA_D_RE.search(name)  # 'D48.6' 形式
        if dm:
            out["diameter_mm"] = float(dm.group(1))
    pair = PAIR_RE.search(name)
    if pair:
        out["width_mm"] = float(pair.group(1))
        out["height_mm"] = float(pair.group(2))
    tm = THICK_RE.search(name) or THICK_T_RE.search(name)
    if tm:
        out["thickness_mm"] = float(tm.group(1))
    elif out["diameter_mm"] is None and out["width_mm"] is None:
        # 「角パイプ_50」のような単一数値は幅候補に
        nums = NUM_RE.findall(name)
        if nums:
            out["width_mm"] = float(nums[0])
    return out


def suggest_calc_type(name: str, detected: Optional[dict] = None) -> str:
    """レイヤー名（＋検出オブジェクト種別）から calc_type を推定。"""
    n = name or ""
    # ASCII命名コード（先頭トークン）を優先判定
    code = _ascii_code(n)
    if code in ASCII_CODE_SPECIAL:
        return ASCII_CODE_SPECIAL[code]
    if code in ASCII_CODE_CAT:
        return _AREA if ASCII_CODE_CAT[code] == "plate" else _STOCK
    if any(h in n for h in IGNORE_HINTS):
        return _IGNORE
    if any(h.upper() in n.upper() for h in COST_HINTS):
        return _FIXED
    if any(h in n for h in COUNT_HINTS):
        return _COUNT
    if any(h.upper() in n.upper() for h in PLATE_HINTS):
        return _AREA
    if any(h.upper() in n.upper() for h in LINEAR_HINTS):
        return _STOCK
    # 名前で決まらない場合は検出オブジェクト種別で補う
    if detected:
        if detected.get("any_curve") and not detected.get("any_brep"):
            return _STOCK
        if detected.get("any_brep") or detected.get("any_mesh"):
            return _VOLUME
        if detected.get("any_surface"):
            return _AREA
    return ""


def suggest_material_category(name: str) -> str:
    code = _ascii_code(name)
    if code in ASCII_CODE_CAT:
        return ASCII_CODE_CAT[code]
    cat = mp.classify_category(name or "")
    return "" if cat == C.UNKNOWN else cat


def suggest_for_layer(name: str, detected: Optional[dict] = None) -> dict:
    """suggest-layer CLI / 雛形生成で使う統合推定。"""
    dims = suggest_dimensions(name)
    calc = suggest_calc_type(name, detected)
    cat = suggest_material_category(name)
    # フラットバーは "幅x厚" 表記（例 FB_SS400_50x4.5）。pair を 幅×厚 と解釈する。
    if cat == "flat_bar" and dims["width_mm"] is not None and dims["thickness_mm"] is None \
            and dims["height_mm"] is not None:
        dims["thickness_mm"] = dims["height_mm"]
        dims["height_mm"] = None
    return {
        "suggested_calc_type": calc,
        "suggested_material_category": cat,
        "suggested_spec_text": (name or "").strip(),
        "suggested_thickness_mm": dims["thickness_mm"],
        "suggested_diameter_mm": dims["diameter_mm"],
        "suggested_width_mm": dims["width_mm"],
        "suggested_height_mm": dims["height_mm"],
    }


# ============================================================
# 集計
# ============================================================

def build_summary(objects: list) -> list[dict]:
    """RhinoObject のリストをレイヤー単位に集計して summary 行を作る。"""
    groups: "OrderedDict[str, list]" = OrderedDict()
    for o in objects:
        groups.setdefault(o.layer_name, []).append(o)

    rows = []
    for layer, objs in groups.items():
        obj_count = sum(int(o.object_count or 1) for o in objs)
        area_mm2 = sum(o.object_area_mm2 or 0.0 for o in objs)
        volume_mm3 = sum(o.object_volume_mm3 or 0.0 for o in objs)
        curve_mm = sum(o.object_curve_length_mm or 0.0 for o in objs)

        types = sorted({o.object_type for o in objs if o.object_type})
        detected = {
            "any_curve": any(o.is_curve or o.is_closed_curve for o in objs),
            "any_brep": any(o.is_closed_brep for o in objs),
            "any_surface": any(o.is_surface for o in objs),
            "any_mesh": any(o.is_mesh for o in objs),
        }

        bbw = max((o.bounding_box_width_mm or 0.0 for o in objs), default=0.0)
        bbh = max((o.bounding_box_height_mm or 0.0 for o in objs), default=0.0)
        bbd = max((o.bounding_box_depth_mm or 0.0 for o in objs), default=0.0)
        bbox_note = f"max W{bbw:g} x H{bbh:g} x D{bbd:g} mm"

        sug = suggest_for_layer(layer, detected)
        cat = sug["suggested_material_category"]

        # === 標準方針(2026-05-31〜): 鋼材はポリサーフェス体積→重量で見積もる ===
        # 鋼材系で体積が取れていれば volume_to_weight を第一候補にする。
        # 体積が無い場合のみ、従来の中心線カーブ方式(curve_length_to_stock)へ fallback。
        calc = sug["suggested_calc_type"]
        if is_steel_volume_layer(layer, cat):
            if volume_mm3 > 0:
                calc = _VOLUME
            elif curve_mm > 0:
                calc = _STOCK  # 中心線のみの特殊ケース（補助・旧仕様）
        elif cat == "plate" or _ascii_code(layer) in ("PL", "PLATE"):
            # 板材: 面積優先。面積が無く体積があるソリッド板は volume_to_weight。
            if area_mm2 <= 0 and volume_mm3 > 0:
                calc = _VOLUME
        sug["suggested_calc_type"] = calc

        warnings = []
        if calc == _AREA and area_mm2 <= 0:
            warnings.append("面積データなし(area=0)")
        if calc == _VOLUME and volume_mm3 <= 0:
            warnings.append("体積データなし(volume=0)")
        if calc in (_STOCK, _METER) and curve_mm <= 0:
            warnings.append("曲線長データなし(length=0)")
        if len(types) > 1:
            warnings.append(f"複数オブジェクト種別が混在: {','.join(types)}")
        if not calc:
            warnings.append("calc_type自動推定できず・要指定")

        rows.append({
            "layer_name": layer,
            "object_count": obj_count,
            "total_area_m2": round(area_mm2 / 1_000_000.0, 6),
            "total_volume_mm3": round(volume_mm3, 3),
            "total_curve_length_m": round(curve_mm / 1000.0, 4),
            "detected_object_types": ",".join(types),
            "bounding_box_note": bbox_note,
            "suggested_calc_type": calc,
            "suggested_material_category": sug["suggested_material_category"],
            "suggested_spec_text": sug["suggested_spec_text"],
            "suggested_thickness_mm": sug["suggested_thickness_mm"],
            "suggested_diameter_mm": sug["suggested_diameter_mm"],
            "suggested_width_mm": sug["suggested_width_mm"],
            "suggested_height_mm": sug["suggested_height_mm"],
            "needs_mapping": "true",
            "warning": "; ".join(warnings),
            "notes": "自動集計。suggested_* は候補であり確定値ではない。",
        })
    return rows


def write_summary(path: str, rows: list[dict]) -> int:
    return cu.write_dicts(path, LAYER_SUMMARY_FIELDS, rows)
