"""estimate-public-rhino / release-audit / mapping-ui(公開データ) のテスト（Phase RC2）。"""

import os

import pytest

from steel_estimator import public_rhino as pr
from steel_estimator import csv_utils as cu


_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SAMPLE = os.path.join(_ROOT, "samples", "rhino_objects_demo.csv")
_PUBLIC = os.path.join(_ROOT, "public_reference_data")


def _run(tmp_path):
    out = str(tmp_path / "out")
    return pr.estimate_public_rhino(_SAMPLE, out, tax_rate=0.10,
                                    public_dir=_PUBLIC, now_str="2026-05-31 03:30:00"), out


def test_estimate_public_rhino_completes(tmp_path):  # 必須1,4
    res, out = _run(tmp_path)
    # ポリサーフェス方針: PL(面積) + 角/丸/FB(体積kg単価) = 4件がmatch。
    # ANGLEは公開参考にkg単価が無い(JIS重量要)ため unmatched=要確認。
    assert len(res["stats"]["matched_layers"]) >= 4
    # 公開価格だけで動く（実DB/実単価を参照しない）
    assert res["plate_csv"].endswith("public_plate_reference_prices.csv")


def test_outputs_created(tmp_path):  # 必須2,3
    _, out = _run(tmp_path)
    for fn in ("layer_summary.csv", "layer_mapping_initial.csv", "layer_mapping_enriched.csv",
               "estimate_result.csv", "estimate_summary.csv", "what_costs_how_much.csv",
               "public_rhino_estimate_report.md"):
        assert os.path.exists(os.path.join(out, fn)), fn


def test_plate_match(tmp_path):  # 必須5
    res, _ = _run(tmp_path)
    assert "PL_SS400_t6" in res["stats"]["matched_layers"]
    w = [x for x in res["what"] if x["layer_name"] == "PL_SS400_t6"][0]
    assert w["price_unit"] == "kg"
    assert float(w["unit_price_ex_tax"]) > 0


def test_square_pipe_match(tmp_path):  # 必須6
    res, _ = _run(tmp_path)
    assert "SQPIPE_STKR_40x40_t2.3" in res["stats"]["matched_layers"]


def test_round_pipe_match(tmp_path):  # 必須7
    res, _ = _run(tmp_path)
    assert "PIPE_STK_D48.6_t2.3" in res["stats"]["matched_layers"]


def test_pricing_modes_present(tmp_path):  # 必須8
    res, _ = _run(tmp_path)
    s = res["stats"]
    assert s["recommended_ex_tax"] > 0
    assert s["conservative_ex_tax"] >= s["recommended_ex_tax"]


def test_tax_ex_and_inc(tmp_path):  # 必須9
    res, _ = _run(tmp_path)
    s = res["stats"]
    assert s["subtotal_ex_tax"] > 0
    assert s["tax_amount"] > 0
    assert s["subtotal_inc_tax"] == s["subtotal_ex_tax"] + s["tax_amount"]


def test_report_content(tmp_path):  # 必須3
    _, out = _run(tmp_path)
    md = open(os.path.join(out, "public_rhino_estimate_report.md"), encoding="utf-8").read()
    assert "公開用参考価格" in md
    assert "税込合計" in md
    assert "何がいくらか" in md


def test_mapping_ui_reads_public_out_dir(tmp_path):  # 必須10
    fastapi = pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from steel_estimator import mapping_ui
    _, out = _run(tmp_path)
    app = mapping_ui.create_app(out)
    client = TestClient(app)
    assert client.get("/").status_code == 200
    assert client.get("/layers").status_code == 200


def test_release_audit_report(tmp_path):  # 必須11
    from steel_estimator import release_audit as ra
    out_md = str(tmp_path / "release_audit_report.md")
    rep = ra.run_release_audit(repo_root=_ROOT, public_dir=_PUBLIC, out=out_md,
                               run_pytest=False, now_str="2026-05-31")
    assert os.path.exists(rep["report_path"])
    names = {c["name"]: c["ok"] for c in rep["checks"]}
    assert names["公開参考価格CSV存在"] is True
    assert names["estimate-public-rhino 完走（サンプル）"] is True
    assert names["run-demo 完走"] is True


def test_public_only_no_real_data(tmp_path):  # 必須4 念押し
    """実DB(data/steel_quotes.sqlite)が無くても完走する。"""
    res, _ = _run(tmp_path)
    assert res["stats"]["subtotal_ex_tax"] > 0
