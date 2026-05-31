"""validate-rhino-csv とエクスポートスクリプト純粋部分のテスト。

Rhino本体は不要。RhinoCommon依存部は export_rhino_objects.main 内に隔離されており、
本テストは純粋関数のみを対象にする。
"""

import importlib.util
import os

import pytest

from steel_estimator import rhino_csv
from steel_estimator import csv_utils as cu


_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SAMPLE = os.path.join(_ROOT, "samples", "rhino_objects.csv")
_EXPORT_PY = os.path.join(_ROOT, "rhino_scripts", "export_rhino_objects.py")


def _load_export_module():
    spec = importlib.util.spec_from_file_location("export_rhino_objects", _EXPORT_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---- validate ----

def test_validate_sample_passes():
    """samples/rhino_objects.csv は validate を通る（必須）。"""
    rep = rhino_csv.validate_rhino_csv(_SAMPLE)
    assert rep["ok"] is True
    assert rep["errors"] == []
    assert rep["stats"]["rows"] > 0
    assert rep["stats"]["layers"] > 0


def test_validate_missing_header(tmp_path):
    p = tmp_path / "bad.csv"
    cu.write_dicts(str(p), ["layer_name", "object_id"],
                   [{"layer_name": "L", "object_id": "1"}])
    rep = rhino_csv.validate_rhino_csv(str(p))
    assert rep["ok"] is False
    assert any("必須ヘッダー" in e for e in rep["errors"])


def test_validate_bad_numeric_and_empty_layer(tmp_path):
    p = tmp_path / "bad2.csv"
    rows = [
        {f: "" for f in rhino_csv.RHINO_OBJECT_FIELDS},
        {f: "" for f in rhino_csv.RHINO_OBJECT_FIELDS},
    ]
    rows[0].update(layer_name="鉄板6mm", object_id="A1", object_area_mm2="abc")
    rows[1].update(layer_name="", object_id="A2", object_area_mm2="100")
    cu.write_dicts(str(p), rhino_csv.RHINO_OBJECT_FIELDS, rows)
    rep = rhino_csv.validate_rhino_csv(str(p))
    assert rep["ok"] is False
    assert any("数値" in e for e in rep["errors"])
    assert any("layer_name" in e for e in rep["errors"])


def test_validate_duplicate_id_warns(tmp_path):
    p = tmp_path / "dup.csv"
    rows = [{f: "" for f in rhino_csv.RHINO_OBJECT_FIELDS} for _ in range(2)]
    rows[0].update(layer_name="L", object_id="SAME", object_area_mm2="1000000")
    rows[1].update(layer_name="L", object_id="SAME", object_curve_length_mm="500")
    cu.write_dicts(str(p), rhino_csv.RHINO_OBJECT_FIELDS, rows)
    rep = rhino_csv.validate_rhino_csv(str(p))
    assert rep["ok"] is True  # 重複は warning（エラーではない）
    assert any("object_id" in w for w in rep["warnings"])


# ---- 単位換算 ----

def test_unit_scale_to_mm():
    assert rhino_csv.unit_scale_to_mm("Millimeters") == (1.0, "")
    assert rhino_csv.unit_scale_to_mm("Meters")[0] == 1000.0
    assert rhino_csv.unit_scale_to_mm("Inches")[0] == 25.4
    s, warn = rhino_csv.unit_scale_to_mm("Furlongs")
    assert s == 1.0 and warn != ""


# ---- export スクリプトの純粋部分 ----

def test_export_pure_functions():
    mod = _load_export_module()
    assert mod.scale_for_unit_name("Meters")[0] == 1000.0
    assert mod.scale_for_unit_name("Feet")[0] == 304.8
    assert mod.scale_for_unit_name("parsecs")[0] == 1.0  # 未対応→1
    assert mod.bool_str(True) == "true"
    assert mod.bool_str(False) == "false"
    assert mod.HEADERS == list(rhino_csv.RHINO_OBJECT_FIELDS)


def test_export_make_row_and_validate(tmp_path):
    """export の make_row→write_csv 出力が validate を通り、summarize互換であること。"""
    mod = _load_export_module()
    rows = [
        mod.make_row("sample.3dm", "鉄板6mm", "G1", "天板", "Surface",
                     area_mm2=1_000_000, bbw=1000, bbh=1000, bbd=6, is_surface=True),
        mod.make_row("sample.3dm", "架台::角パイプ_50", "G2", "脚", "Curve",
                     curve_len_mm=6000, bbw=50, bbh=50, bbd=6000, is_curve=True),
        mod.make_row("sample.3dm", "金物::ブロック", "G3", "", "InstanceObject",
                     bbw=100, bbh=100, bbd=100, notes="block instance not expanded"),
    ]
    p = tmp_path / "rhino_objects.csv"
    n = mod.write_csv(str(p), rows)
    assert n == 3
    # UTF-8 BOM で書かれている
    with open(p, "rb") as f:
        assert f.read(3) == b"\xef\xbb\xbf"
    # validate を通る
    rep = rhino_csv.validate_rhino_csv(str(p))
    assert rep["ok"] is True
    # 既存の読込で日本語・階層レイヤー名が保持される
    objs = rhino_csv.read_rhino_objects(str(p))
    assert objs[1].layer_name == "架台::角パイプ_50"
    assert objs[0].is_surface is True
