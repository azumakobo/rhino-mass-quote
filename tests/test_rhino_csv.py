"""rhino_objects.csv 読み込みと UTF-8 BOM 入出力のテスト。"""

import os

from steel_estimator import csv_utils as cu
from steel_estimator import rhino_csv
from steel_estimator.rhino_csv import RHINO_OBJECT_FIELDS


SAMPLE_ROWS = [
    {"file_name": "x.3dm", "layer_name": "鉄板6mm", "object_id": "1",
     "object_name": "天板", "object_type": "Surface", "object_count": "2",
     "object_area_mm2": "1000000", "object_volume_mm3": "", "object_curve_length_mm": "",
     "bounding_box_width_mm": "1000", "bounding_box_height_mm": "1000",
     "bounding_box_depth_mm": "6", "is_closed_curve": "false", "is_closed_brep": "false",
     "is_surface": "true", "is_mesh": "false", "is_curve": "false", "notes": "日本語メモ"},
    {"file_name": "x.3dm", "layer_name": "角パイプ_50 (脚)", "object_id": "2",
     "object_name": "脚", "object_type": "Curve", "object_count": "1",
     "object_area_mm2": "", "object_volume_mm3": "", "object_curve_length_mm": "6000",
     "bounding_box_width_mm": "50", "bounding_box_height_mm": "50",
     "bounding_box_depth_mm": "6000", "is_closed_curve": "false", "is_closed_brep": "false",
     "is_surface": "false", "is_mesh": "false", "is_curve": "true", "notes": ""},
]


def test_read_japanese_layer_names(tmp_path):
    """日本語・スペース・記号を含む rhino_objects.csv を読み込める（必須1）。"""
    p = tmp_path / "rhino_objects.csv"
    cu.write_dicts(str(p), RHINO_OBJECT_FIELDS, SAMPLE_ROWS)
    objs = rhino_csv.read_rhino_objects(str(p))
    assert len(objs) == 2
    assert objs[0].layer_name == "鉄板6mm"
    assert objs[1].layer_name == "角パイプ_50 (脚)"
    assert objs[0].object_count == 2
    assert objs[0].object_area_mm2 == 1000000.0
    assert objs[0].is_surface is True
    assert objs[1].is_curve is True
    assert objs[0].notes == "日本語メモ"


def test_utf8_bom_roundtrip(tmp_path):
    """UTF-8 with BOM で書き出し・読み込みできる（必須19）。"""
    p = tmp_path / "bom.csv"
    cu.write_dicts(str(p), ["layer_name", "value"],
                   [{"layer_name": "鉄板6mm", "value": "123"}])
    with open(p, "rb") as f:
        head = f.read(3)
    assert head == b"\xef\xbb\xbf"  # BOM が先頭にある
    rows = cu.read_dicts(str(p))
    assert rows[0]["layer_name"] == "鉄板6mm"  # BOMがキーに混入しない
    assert rows[0]["value"] == "123"
