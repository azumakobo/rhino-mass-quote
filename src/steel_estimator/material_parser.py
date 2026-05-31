"""材料分類・規格抽出・寸法パース。

2つの経路で共有される純粋ロジック層:
  - テーブル経路（pdf_extract が列を渡す）
  - フリーテキスト経路（行文字列を渡す）

外部I/Oを持たず、文字列 → 構造化値のみを担う。
"""

from __future__ import annotations

import re
from typing import Optional

from .models import MaterialCategory as C


# --- 分類キーワード（順序が優先度。前方ほど強い一致） ---
# 注: 「STKR」は角パイプ、「STK」は丸パイプなので STKR を先に判定する。
CATEGORY_RULES = [
    (C.SQUARE_PIPE, ("角パイプ", "角鋼管", "STKR", "STKMR", "□", "BOX", "ボックス")),
    (C.ROUND_PIPE, ("丸パイプ", "丸鋼管", "STK", "SGP", "鋼管")),
    (C.ANGLE, ("アングル", "等辺山形鋼", "山形鋼", "Lアングル", "L-", "Ｌアングル")),
    (C.CHANNEL, ("チャンネル", "Cチャン", "溝形鋼", "C-", "Ｃチャン")),
    (C.FLAT_BAR, ("フラットバー", "平鋼", "FB", "ＦＢ")),
    (C.H_BEAM, ("H形鋼", "Ｈ形鋼", "H鋼", "Ｈ鋼", "I形鋼")),
    (C.ROLLED, ("ロール巻き", "ロール巻", "巻き")),
    (C.ROUND_BAR, ("丸棒", "丸鋼", "ミガキ丸", "RB", "ＲＢ")),
    (C.SQUARE_BAR, ("角棒", "角鋼")),
    (C.PLATE, ("縞鋼板", "鋼板", "鉄板", "切板", "型切", "プレート", "PL", "ＰＬ", "板")),
]

# 材質グレード抽出パターン（長いものを先に）
GRADE_PATTERNS = [
    r"SUS\s?316L?", r"SUS\s?304", r"SUS\s?430",
    r"STKMR?\d*", r"STKR\d*", r"STK\d+", r"STK",
    r"SGP", r"SS400", r"S\d{2}C", r"SPHC", r"SPCC",
    r"A\d{4}", r"AL", r"アルミ",
]
GRADE_RE = re.compile("(" + "|".join(GRADE_PATTERNS) + ")", re.IGNORECASE)

# φ 値（外径/径）
PHI_RE = re.compile(r"[φΦ]\s?(\d+(?:\.\d+)?)")
# 厚み t 値
THICK_RE = re.compile(r"(?:^|[^A-Za-z])t\s?(\d+(?:\.\d+)?)", re.IGNORECASE)
# 数値（カンマ区切り対応）
NUM_RE = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?")
# 長さの「m」表記（mm は除外）: 6m, 5.5m
METER_RE = re.compile(r"(\d+(?:\.\d+)?)\s?m(?![m\d])")


def normalize_number(s: Optional[str]) -> Optional[float]:
    """カンマ・空白・全角を除去して float 化。失敗時 None。"""
    if s is None:
        return None
    s = str(s).strip().replace(",", "").replace("，", "")
    s = s.translate(str.maketrans("０１２３４５６７８９．", "0123456789."))
    if not s:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    if not m:
        return None
    try:
        return float(m.group())
    except ValueError:
        return None


def parse_length_token(s: Optional[str]) -> Optional[float]:
    """長さトークンを mm に正規化。'6m'→6000, '5.5m'→5500, '6000'→6000。"""
    if s is None:
        return None
    s = str(s).strip()
    mm = METER_RE.search(s)
    if mm:
        return float(mm.group(1)) * 1000.0
    return normalize_number(s)


def parse_pair(s: Optional[str]) -> tuple[Optional[float], Optional[float]]:
    """'40x40' / '100×50' / '75X45' → (40.0, 40.0)。単一値なら (v, None)。"""
    if s is None:
        return (None, None)
    parts = re.split(r"[x×X*／/]", str(s))
    nums = [normalize_number(p) for p in parts if normalize_number(p) is not None]
    if not nums:
        return (None, None)
    if len(nums) == 1:
        return (nums[0], None)
    return (nums[0], nums[1])


def extract_grade(text: str) -> str:
    """文字列から材質グレードを抽出。見つからなければ空文字。"""
    if not text:
        return ""
    m = GRADE_RE.search(text)
    if not m:
        return ""
    g = m.group(1).upper().replace(" ", "")
    if g in ("アルミ", "AL"):
        return "AL"
    return g


def detect_shape_token(text: str, category: str) -> str:
    """代表的な形状トークンを返す（φ, □, L, C, PL, FB など）。"""
    if "φ" in text or "Φ" in text:
        return "φ"
    mapping = {
        C.SQUARE_PIPE: "□",
        C.ANGLE: "L",
        C.CHANNEL: "C",
        C.FLAT_BAR: "FB",
        C.PLATE: "PL",
        C.ROUND_PIPE: "φ",
        C.ROUND_BAR: "φ",
    }
    return mapping.get(category, "")


def classify_category(text: str) -> str:
    """品名・形状文字列から材料カテゴリを判定。"""
    if not text:
        return C.UNKNOWN
    t = text.upper()
    for category, keywords in CATEGORY_RULES:
        for kw in keywords:
            if kw.upper() in t:
                return category
    return C.UNKNOWN


def parse_dimension_text(text: str, category: str) -> dict:
    """フリーテキストの寸法表記をカテゴリ依存で構造化する。

    返り値キー: diameter_mm, width_mm, height_mm, thickness_mm, length_mm,
                plate_width_mm, plate_height_mm, needs_review, notes
    対応例:
      丸パイプ φ48.6×t2.3×6000 / 角パイプ □50×50×2.3×6m /
      L-50×50×6 / PL 6×914×1829 / SS400 t9 4×8
    """
    out = {
        "diameter_mm": None, "width_mm": None, "height_mm": None,
        "thickness_mm": None, "length_mm": None,
        "plate_width_mm": None, "plate_height_mm": None,
        "needs_review": False, "notes": "",
    }
    if not text:
        out["needs_review"] = True
        return out

    phi = PHI_RE.search(text)
    diameter = float(phi.group(1)) if phi else None
    thick_m = THICK_RE.search(text)
    thickness = float(thick_m.group(1)) if thick_m else None
    meter = METER_RE.search(text)
    length_m = float(meter.group(1)) * 1000.0 if meter else None

    # マーカー（φ, tN, Nm）と材質グレード（SS400 等の数字混じり）を消してから
    # 「素の寸法数値」を抽出する。
    masked = GRADE_RE.sub(" ", text)
    if phi:
        masked = masked.replace(phi.group(0), " ")
    if thick_m:
        masked = masked.replace(thick_m.group(0), " ")
    if meter:
        masked = masked.replace(meter.group(0), " ")
    plains = [normalize_number(m) for m in NUM_RE.findall(masked)]
    plains = [p for p in plains if p is not None]

    def take(i):
        return plains[i] if i < len(plains) else None

    if category == C.ROUND_PIPE:
        out["diameter_mm"] = diameter
        out["thickness_mm"] = thickness if thickness is not None else take(0)
        length = length_m if length_m is not None else (take(0) if thickness is not None else take(1))
        out["length_mm"] = length
        if diameter is None:
            out["needs_review"] = True

    elif category == C.ROUND_BAR:
        out["diameter_mm"] = diameter if diameter is not None else take(0)
        out["length_mm"] = length_m if length_m is not None else (take(0) if diameter is not None else take(1))
        if out["diameter_mm"] is None:
            out["needs_review"] = True

    elif category in (C.SQUARE_PIPE, C.ANGLE, C.CHANNEL):
        # W × H × t (× L)
        out["width_mm"] = take(0)
        out["height_mm"] = take(1)
        if thickness is not None:
            out["thickness_mm"] = thickness
            out["length_mm"] = length_m if length_m is not None else take(2)
        else:
            out["thickness_mm"] = take(2)
            out["length_mm"] = length_m if length_m is not None else take(3)
        if out["width_mm"] is None or out["thickness_mm"] is None:
            out["needs_review"] = True

    elif category == C.FLAT_BAR:
        # FB: t × W (× L) もしくは W × t
        out["thickness_mm"] = thickness if thickness is not None else take(0)
        out["width_mm"] = take(0) if thickness is not None else take(1)
        out["length_mm"] = length_m if length_m is not None else take(2 if thickness is not None else 2)
        if out["thickness_mm"] is None:
            out["needs_review"] = True

    elif category == C.PLATE:
        # PL t × 幅 × 高、もしくは t9 4×8（尺表記疑い）
        out["thickness_mm"] = thickness if thickness is not None else take(0)
        rest = plains[1:] if thickness is None else plains
        # 尺表記疑い: 小さい整数ペア（< 20）で plate寸法に整合しない
        small_pair = [v for v in rest if v is not None and v < 20]
        if thickness is not None and len(plains) == 2 and all(v < 20 for v in plains):
            # 例 "SS400 t9 4×8": 4×8 は尺の可能性。マッピング不明 → review。
            out["needs_review"] = True
            out["notes"] = "尺表記の可能性(4x8等)。plate寸法は未確定。"
        else:
            if thickness is not None:
                out["plate_width_mm"] = take(0)
                out["plate_height_mm"] = take(1)
            else:
                out["plate_width_mm"] = take(1)
                out["plate_height_mm"] = take(2)
        if out["thickness_mm"] is None:
            out["needs_review"] = True

    else:  # UNKNOWN / SQUARE_BAR / H_BEAM / ROLLED は最小限
        out["diameter_mm"] = diameter
        out["thickness_mm"] = thickness
        out["length_mm"] = length_m
        out["needs_review"] = True

    return out
