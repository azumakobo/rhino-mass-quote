"""material_parser の分類・寸法パースのテスト。

仕様書の寸法例を中心に検証する。
"""

import pytest

from steel_estimator import material_parser as mp
from steel_estimator.models import MaterialCategory as C


# ---- 分類 ----

@pytest.mark.parametrize("text,expected", [
    ("丸パイプ φ48.6×t2.3×6000", C.ROUND_PIPE),
    ("角パイプ □50×50×2.3×6m", C.SQUARE_PIPE),
    ("L-50×50×6", C.ANGLE),
    ("アングル SS400 40x40", C.ANGLE),
    ("PL 6×914×1829", C.PLATE),
    ("切板 SS400 4.5 300 300", C.PLATE),
    ("型切", C.PLATE),
    ("丸棒 S45C φ50", C.ROUND_BAR),
    ("FB SS400 6×50", C.FLAT_BAR),
    ("チャンネル C-100×50", C.CHANNEL),
    ("H形鋼 100x100", C.H_BEAM),
    ("STKR 角パイプ", C.SQUARE_PIPE),
    ("STK400 丸パイプ", C.ROUND_PIPE),
    ("謎の品目", C.UNKNOWN),
])
def test_classify(text, expected):
    assert mp.classify_category(text) == expected


# ---- 材質グレード ----

@pytest.mark.parametrize("text,expected", [
    ("丸パイプ SUS304", "SUS304"),
    ("SS400 t9", "SS400"),
    ("STKR400 角パイプ", "STKR400"),
    ("丸棒 S45C", "S45C"),
    ("STK400", "STK400"),
    ("A5052 アルミ", "A5052"),
])
def test_extract_grade(text, expected):
    assert mp.extract_grade(text) == expected


# ---- 数値正規化 ----

def test_normalize_number():
    assert mp.normalize_number("1,880") == 1880.0
    assert mp.normalize_number("48.6") == 48.6
    assert mp.normalize_number("") is None
    assert mp.normalize_number("φ27.2") == 27.2


def test_parse_length_token():
    assert mp.parse_length_token("6m") == 6000.0
    assert mp.parse_length_token("5.5m") == 5500.0
    assert mp.parse_length_token("6000") == 6000.0
    assert mp.parse_length_token("5500") == 5500.0


def test_parse_pair():
    assert mp.parse_pair("40x40") == (40.0, 40.0)
    assert mp.parse_pair("100×50") == (100.0, 50.0)
    assert mp.parse_pair("75X45") == (75.0, 45.0)
    assert mp.parse_pair("50") == (50.0, None)


# ---- 寸法パース（仕様書の代表例） ----

def test_round_pipe():
    d = mp.parse_dimension_text("丸パイプ φ48.6×t2.3×6000", C.ROUND_PIPE)
    assert d["diameter_mm"] == 48.6
    assert d["thickness_mm"] == 2.3
    assert d["length_mm"] == 6000.0
    assert d["needs_review"] is False


def test_square_pipe():
    d = mp.parse_dimension_text("角パイプ □50×50×2.3×6m", C.SQUARE_PIPE)
    assert d["width_mm"] == 50.0
    assert d["height_mm"] == 50.0
    assert d["thickness_mm"] == 2.3
    assert d["length_mm"] == 6000.0


def test_angle():
    d = mp.parse_dimension_text("L-50×50×6", C.ANGLE)
    assert d["width_mm"] == 50.0
    assert d["height_mm"] == 50.0
    assert d["thickness_mm"] == 6.0


def test_plate_pl():
    d = mp.parse_dimension_text("PL 6×914×1829", C.PLATE)
    assert d["thickness_mm"] == 6.0
    assert d["plate_width_mm"] == 914.0
    assert d["plate_height_mm"] == 1829.0
    assert d["needs_review"] is False


def test_plate_ambiguous_shaku():
    d = mp.parse_dimension_text("SS400 t9 4×8", C.PLATE)
    assert d["thickness_mm"] == 9.0
    # 4×8 は尺表記の可能性 → plate寸法は確定させず needs_review
    assert d["plate_width_mm"] is None
    assert d["plate_height_mm"] is None
    assert d["needs_review"] is True
