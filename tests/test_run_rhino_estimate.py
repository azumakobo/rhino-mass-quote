"""run-rhino-estimate 一括フローのテスト。"""

import os

import pytest

from steel_estimator import rhino_run
from steel_estimator import rhino_csv
from steel_estimator import layer_mapping as lmap
from steel_estimator import csv_utils as cu


_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SAMPLE = os.path.join(_ROOT, "samples", "rhino_objects.csv")
_COST = os.path.join(_ROOT, "samples", "cost_items.csv")


def test_run_full_flow_from_sample(tmp_path):  # 必須1,5
    out = tmp_path / "out"
    res = rhino_run.run_rhino_estimate(
        rhino_csv_path=_SAMPLE, mapping_path=None, cost_items_path=_COST,
        out_dir=str(out), now_str="2026-05-31 12:00:00")
    # 出力ファイルが揃う
    for key in ("summary_path", "mapping_out", "result_path", "summary_out", "report_path"):
        assert os.path.exists(res[key]), key
    assert res["mapping_mode"] == "init"
    assert os.path.basename(res["mapping_out"]) == "layer_mapping.csv"
    assert os.path.exists(os.path.join(str(out), "estimate_summary.csv"))


def test_existing_mapping_preserved_only_new_added(tmp_path):  # 必須2
    out = tmp_path / "out"
    # 既存mapping（鉄板6mmだけ・人間が単価確定済み）
    existing_path = tmp_path / "layer_mapping.csv"
    existing = [{
        **{f: "" for f in lmap.MAPPING_FIELDS},
        "layer_name": "鉄板6mm", "enabled": "true", "calc_type": "area_to_weight",
        "thickness_mm": "6", "density_g_cm3": "7.85", "unit_price": "150",
        "price_unit": "kg", "waste_rate": "1.1", "notes": "確定済み",
    }]
    lmap.write_mapping(str(existing_path), existing)

    res = rhino_run.run_rhino_estimate(
        rhino_csv_path=_SAMPLE, mapping_path=str(existing_path), cost_items_path=None,
        out_dir=str(out), now_str="2026-05-31 12:00:00")
    assert res["mapping_mode"] == "updated"
    assert os.path.basename(res["mapping_out"]) == "layer_mapping_updated.csv"

    # 元ファイルは変更されない（1行のまま）
    orig = lmap.read_mapping(str(existing_path))
    assert len(orig) == 1
    assert orig[0]["unit_price"] == "150"

    # updated は既存行の値を保持し、新規レイヤーが追加されている
    updated = lmap.read_mapping(res["mapping_out"])
    teppan = [r for r in updated if r["layer_name"] == "鉄板6mm"][0]
    assert teppan["unit_price"] == "150"
    assert teppan["notes"] == "確定済み"
    assert len(updated) > 1
    assert "鉄板6mm" not in res["added_layers"]
    assert len(res["added_layers"]) == len(updated) - 1


def test_report_contains_unmapped_and_review(tmp_path):  # 必須3,4,5
    out = tmp_path / "out"
    res = rhino_run.run_rhino_estimate(
        rhino_csv_path=_SAMPLE, mapping_path=None, cost_items_path=_COST,
        out_dir=str(out), now_str="2026-05-31 12:00:00")
    md = open(res["report_path"], encoding="utf-8").read()
    assert "mapping未設定" in md
    assert "needs_review件数" in md
    assert "カテゴリ別小計" in md
    assert "次に編集すべきファイル" in md
    # 雛形は単価未入力なので needs_review が発生する
    assert res["stats"]["needs_review"] > 0
    assert res["stats"]["unmapped"] > 0


def test_missing_header_stops(tmp_path):  # 処理不能時のみ停止
    bad = tmp_path / "bad.csv"
    cu.write_dicts(str(bad), ["layer_name", "object_id"],
                   [{"layer_name": "L", "object_id": "1"}])
    with pytest.raises(rhino_run.RhinoEstimateError):
        rhino_run.run_rhino_estimate(
            rhino_csv_path=str(bad), mapping_path=None, cost_items_path=None,
            out_dir=str(tmp_path / "out"))


def test_scripts_exist_and_executable():  # 必須9,10
    for name in ("open_rhino_export_helper.sh", "copy_rhino_script_path.sh"):
        p = os.path.join(_ROOT, "scripts", name)
        assert os.path.exists(p), p
        assert os.access(p, os.X_OK), f"{name} に実行権限がありません"
