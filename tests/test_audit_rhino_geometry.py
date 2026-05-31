"""audit-rhino-geometry のテスト。"""

import os

from steel_estimator import rhino_audit
from steel_estimator import rhino_csv
from steel_estimator import csv_utils as cu


def _write(tmp_path, rows):
    p = tmp_path / "rhino_objects.csv"
    full = []
    for r in rows:
        base = {f: "" for f in rhino_csv.RHINO_OBJECT_FIELDS}
        base.update(r)
        full.append(base)
    cu.write_dicts(str(p), rhino_csv.RHINO_OBJECT_FIELDS, full)
    return str(p)


def _codes(rep):
    return {f["code"] for f in rep["findings"]}


def test_detect_zero_geometry(tmp_path):  # 必須6
    p = _write(tmp_path, [
        {"layer_name": "謎レイヤー", "object_id": "1", "object_type": "Other"},
        {"layer_name": "鉄板", "object_id": "2", "object_type": "Surface",
         "object_area_mm2": "1000000"},
    ])
    rep = rhino_audit.audit_rhino_geometry(p)
    assert "zero_geometry" in _codes(rep)


def test_detect_block_instance(tmp_path):  # 必須7
    p = _write(tmp_path, [
        {"layer_name": "金物", "object_id": "1", "object_type": "InstanceObject",
         "bounding_box_width_mm": "100", "bounding_box_height_mm": "100",
         "bounding_box_depth_mm": "100", "notes": "block instance not expanded"},
    ])
    rep = rhino_audit.audit_rhino_geometry(p)
    assert "block_instance" in _codes(rep)
    blk = [f for f in rep["findings"] if f["code"] == "block_instance"][0]
    assert blk["severity"] == "info"


def test_japanese_layer_names_preserved(tmp_path):  # 必須8
    p = _write(tmp_path, [
        {"layer_name": "架台::角パイプ_50 (脚)", "object_id": "1", "object_type": "Curve",
         "object_curve_length_mm": "6000", "is_curve": "true"},
    ])
    rep = rhino_audit.audit_rhino_geometry(p)
    md = rhino_audit.render_markdown(rep, p, "2026-05-31 00:00:00")
    # 監査でレイヤー名が文字化け・欠損しない
    assert isinstance(md, str)
    assert rep["stats"]["layers"] == 1


def test_empty_layer_is_error(tmp_path):
    p = _write(tmp_path, [
        {"layer_name": "", "object_id": "1", "object_type": "Curve",
         "object_curve_length_mm": "100", "is_curve": "true"},
    ])
    rep = rhino_audit.audit_rhino_geometry(p)
    errs = [f for f in rep["findings"] if f["severity"] == "error"]
    assert any(f["code"] == "empty_layer" for f in errs)


def test_open_curve_on_plate_layer_warns(tmp_path):
    p = _write(tmp_path, [
        {"layer_name": "鉄板6mm", "object_id": "1", "object_type": "Curve",
         "object_curve_length_mm": "4000", "is_curve": "true", "is_closed_curve": "false"},
    ])
    rep = rhino_audit.audit_rhino_geometry(p)
    assert "open_curve_area" in _codes(rep)


def test_markdown_on_clean_csv(tmp_path):
    p = _write(tmp_path, [
        {"layer_name": "鉄板", "object_id": "1", "object_type": "Surface",
         "object_area_mm2": "1000000", "is_surface": "true",
         "bounding_box_width_mm": "1000", "bounding_box_height_mm": "1000",
         "bounding_box_depth_mm": "6"},
    ])
    rep = rhino_audit.audit_rhino_geometry(p)
    out = tmp_path / "audit.md"
    rhino_audit.write_audit_md(rep, p, str(out), "2026-05-31")
    assert os.path.exists(out)
