"""Rhinoスクリプトの堅牢性・存在確認・差分比較（Phase RC3）。

Rhino本体は不要。RhinoCommon依存部は main() 内に隔離されているため、通常Pythonでも
import は落ちず、main() は分かりやすいエラーを出すことを確認する。
"""

import importlib.util
import os

import pytest

from steel_estimator import rhino_csv


_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPTS = os.path.join(_ROOT, "rhino_scripts")
_DOCS = os.path.join(_ROOT, "docs")
_SAMPLE = os.path.join(_ROOT, "samples", "rhino_objects_demo.csv")


def _load(name):
    spec = importlib.util.spec_from_file_location(name[:-3], os.path.join(_SCRIPTS, name))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # import時に落ちないこと（必須1）
    return mod


def test_create_demo_exists():  # 必須2
    assert os.path.exists(os.path.join(_SCRIPTS, "create_demo_rhino_model.py"))


def test_export_exists():  # 必須3
    assert os.path.exists(os.path.join(_SCRIPTS, "export_rhino_objects.py"))


@pytest.mark.parametrize("script", ["create_demo_rhino_model.py", "export_rhino_objects.py"])
def test_scripts_import_and_friendly_error(script):  # 必須1
    mod = _load(script)
    assert hasattr(mod, "running_in_rhino")
    assert mod.running_in_rhino() is False  # 通常Pythonでは Rhino 不在
    with pytest.raises(RuntimeError) as ei:
        mod.main()
    assert "Rhino" in str(ei.value)  # 分かりやすいメッセージ


def test_demo_layers_cover_required():
    """実運用に近いレイヤー名の単純Box（断面再現なし）。"""
    mod = _load("create_demo_rhino_model.py")
    names = [n for n, _, _ in mod.DEMO_LAYERS]
    for required in ("PL_SS400_t6", "PL_SS400_t9", "SQPIPE_STKR_40x40_t2.3",
                     "PIPE_STK_D48.6_t2.3", "FB_SS400_50x4.5", "ANGLE_SS400_40x40_t3",
                     "BOLT_TEST", "IGNORE_GUIDE"):
        assert required in names


def test_checklist_doc_exists():  # 必須4
    assert os.path.exists(os.path.join(_DOCS, "rhino-manual-test-checklist.md"))


def test_result_template_doc_exists():  # 必須5
    assert os.path.exists(os.path.join(_DOCS, "rhino-manual-test-result-template.md"))


def test_compare_rhino_csv_identical():
    """同一CSV同士の比較は一致（重大差分なし）。"""
    rep = rhino_csv.compare_rhino_csv(_SAMPLE, _SAMPLE)
    assert rep["ok"] is True
    assert rep["missing_in_actual"] == []
    assert rep["extra_in_actual"] == []


def test_compare_rhino_csv_detects_missing(tmp_path):
    from steel_estimator import csv_utils as cu
    rows = cu.read_dicts(_SAMPLE)
    # 1レイヤー欠落＋面積を0に
    partial = [r for r in rows if r["layer_name"] != "ANGLE_SS400_40x40_t3"]
    for r in partial:
        if r["layer_name"] == "PL_SS400_t6":
            r["object_area_mm2"] = "0"
    actual = tmp_path / "actual.csv"
    cu.write_dicts(str(actual), rhino_csv.RHINO_OBJECT_FIELDS, partial)
    rep = rhino_csv.compare_rhino_csv(_SAMPLE, str(actual))
    assert "ANGLE_SS400_40x40_t3" in rep["missing_in_actual"]
    assert rep["ok"] is False
    md = rhino_csv.render_compare_md(rep, _SAMPLE, str(actual), "2026-05-31")
    assert "差分レポート" in md
