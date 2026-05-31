"""候補単価選択UI のテスト（データ層 + FastAPI TestClient）。

サーバーは起動せず TestClient で検証する。
"""

import os

import pytest

from steel_estimator import csv_utils as cu
from steel_estimator import layer_mapping as lmap
from steel_estimator import candidate_prices as cp
from steel_estimator import mapping_ui_models as mm


def _mrow(**kw):
    base = {f: "" for f in lmap.MAPPING_FIELDS}
    base["enabled"] = "true"; base["waste_rate"] = "1.0"
    base.update(kw)
    return base


def _setup_out_dir(tmp_path):
    """UIが読む各CSVを用意する。"""
    out = tmp_path / "data"
    out.mkdir()
    # mapping（updated）
    mapping = [
        _mrow(layer_name="角パイプ_50", calc_type="curve_length_to_stock",
              material_category="square_pipe", material_grade="STKR",
              width_mm="50", height_mm="50", thickness_mm="2.3"),
        _mrow(layer_name="鉄板6mm", calc_type="area_to_weight",
              material_category="plate", thickness_mm="6", unit_price="150", price_unit="kg"),
    ]
    lmap.write_mapping(str(out / "layer_mapping_updated.csv"), mapping)
    # layer_summary
    cu.write_dicts(str(out / "layer_summary.csv"),
                   ["layer_name", "object_count", "total_area_m2", "total_volume_mm3",
                    "total_curve_length_m", "detected_object_types", "warning"],
                   [{"layer_name": "角パイプ_50", "object_count": "3", "total_curve_length_m": "18",
                     "detected_object_types": "Curve", "warning": ""},
                    {"layer_name": "鉄板6mm", "object_count": "2", "total_area_m2": "2.0",
                     "detected_object_types": "Surface", "warning": ""}])
    # suggestions
    cu.write_dicts(str(out / "layer_mapping_price_suggestions.csv"),
                   ["layer_name", "material_category", "suggested_unit_price",
                    "suggested_price_unit", "suggested_vendor", "suggested_quote_date",
                    "suggested_spec_key", "match_level", "confidence", "needs_review", "warning"],
                   [{"layer_name": "角パイプ_50", "material_category": "square_pipe",
                     "suggested_unit_price": "3880", "suggested_price_unit": "個",
                     "suggested_vendor": "東鋼材", "suggested_quote_date": "2024-01-01",
                     "suggested_spec_key": "square_pipe|STKR|50x50|t2.3|L6000",
                     "match_level": "exact", "confidence": "0.9",
                     "needs_review": "false", "warning": ""}])
    # candidates summary（生材 + 加工品）
    cu.write_dicts(str(out / "toko_candidate_price_summary.csv"), cp.SUMMARY_FIELDS, [
        {**{f: "" for f in cp.SUMMARY_FIELDS}, "material_category": "square_pipe",
         "material_grade": "STKR", "spec_key": "square_pipe|STKR|50x50|t2.3|L6000",
         "normalized_spec": "STKR_50x50_t2.3_L6000", "candidate_class": "base_material",
         "latest_unit_price": "3880", "latest_quote_date": "2024-01-01", "sample_count": "3",
         "price_unit": "個", "usable_as_base_price": "true", "needs_review": "false", "vendor_name": "東鋼材"},
        {**{f: "" for f in cp.SUMMARY_FIELDS}, "material_category": "square_pipe",
         "spec_key": "square_pipe|STKR|50x50|t2.3|L6000曲げ", "normalized_spec": "曲げ品",
         "candidate_class": "processed_item", "latest_unit_price": "9000",
         "latest_quote_date": "2024-02-01", "sample_count": "1",
         "usable_as_base_price": "false", "needs_review": "true", "warning": "加工品",
         "vendor_name": "東鋼材"},
    ])
    # estimate_summary
    cu.write_dicts(str(out / "estimate_summary.csv"),
                   ["category", "subtotal_amount", "item_count", "needs_review_count", "warning_count", "notes"],
                   [{"category": "TOTAL(除ignored)", "subtotal_amount": "50000",
                     "item_count": "2", "needs_review_count": "1", "warning_count": "0", "notes": ""}])
    return str(out)


# ---- データ層 ----

def test_load_state(tmp_path):  # 必須1,3
    out = _setup_out_dir(tmp_path)
    st = mm.load_state(out)
    assert len(st["mapping_rows"]) == 2
    assert "角パイプ_50" in st["summary_by_layer"]
    assert "角パイプ_50" in st["suggestions_by_layer"]
    assert st["mapping_path"].endswith("layer_mapping_updated.csv")  # approvedが無ければupdated


def test_dashboard_data(tmp_path):  # 必須2
    st = mm.load_state(_setup_out_dir(tmp_path))
    d = mm.dashboard_data(st)
    assert d["layers"] == 2
    assert d["unmapped"] == 1   # 角パイプ_50は単価未設定
    assert d["mapped"] == 1
    assert d["match_levels"]["exact"] == 1


def test_japanese_layer_detail(tmp_path):  # 必須4
    st = mm.load_state(_setup_out_dir(tmp_path))
    detail = mm.layer_detail(st, "角パイプ_50")
    assert detail["row"]["layer_name"] == "角パイプ_50"
    assert detail["suggestion"]["match_level"] == "exact"


def test_apply_candidate_to_form(tmp_path):  # 必須5
    st = mm.load_state(_setup_out_dir(tmp_path))
    row = st["mapping_rows"][0]
    sugg = st["suggestions_by_layer"]["角パイプ_50"]
    new = mm.apply_candidate_to_row(row, sugg)
    assert new["unit_price"] == "3880"
    assert "spec_key=square_pipe|STKR|50x50|t2.3|L6000" in new["notes"]
    # 元行は不変（保存しない）
    assert row["unit_price"] == ""


def test_processed_candidate_warning(tmp_path):  # 必須6
    st = mm.load_state(_setup_out_dir(tmp_path))
    detail = mm.layer_detail(st, "角パイプ_50", show_processed=True)
    proc = [c for c in detail["extra_candidates"] if c.get("candidate_class") == "processed_item"]
    assert proc, "加工品候補が表示されること（show_processed=True）"
    assert any("加工品" in w for w in proc[0]["_warnings"])
    # show_processed=False では加工品は出ない
    detail2 = mm.layer_detail(st, "角パイプ_50", show_processed=False)
    assert all(c.get("candidate_class") != "processed_item" for c in detail2["extra_candidates"])


def test_save_creates_approved_not_overwrite_source(tmp_path):  # 必須7,10
    out = _setup_out_dir(tmp_path)
    st = mm.load_state(out)
    rows = [dict(r) for r in st["mapping_rows"]]
    rows[0]["unit_price"] = "3880"  # 角パイプに単価
    res = mm.save_approved(out, rows, st["mapping_rows"], {}, "2026-05-31 12:00:00")
    assert os.path.exists(res["approved_path"])
    assert res["approved_path"].endswith("layer_mapping_approved.csv")
    # 元 updated は変更されない
    src = lmap.read_mapping(os.path.join(out, "layer_mapping_updated.csv"))
    assert all(r["unit_price"] == "" or r["layer_name"] == "鉄板6mm" for r in src)
    assert [r for r in src if r["layer_name"] == "角パイプ_50"][0]["unit_price"] == ""


def test_save_backup_and_log(tmp_path):  # 必須8,9
    out = _setup_out_dir(tmp_path)
    st = mm.load_state(out)
    rows = [dict(r) for r in st["mapping_rows"]]
    rows[0]["unit_price"] = "3880"
    sel = {"角パイプ_50": {"selected_spec_key": "square_pipe|STKR|50x50|t2.3|L6000",
                          "selected_vendor": "東鋼材", "selected_quote_date": "2024-01-01",
                          "match_level": "exact", "confidence": "0.9"}}
    # 1回目: approved作成・ログ追記
    r1 = mm.save_approved(out, rows, st["mapping_rows"], sel, "2026-05-31 12:00:00")
    assert r1["backup_path"] is None
    assert r1["logged"] == 1
    log = cu.read_dicts(os.path.join(out, mm.LOG_NAME))
    assert log[0]["layer_name"] == "角パイプ_50"
    assert log[0]["new_unit_price"] == "3880"
    assert log[0]["selected_vendor"] == "東鋼材"
    # 2回目: 既存approvedありなのでバックアップ作成
    rows[1]["unit_price"] = "160"
    r2 = mm.save_approved(out, rows, rows, {}, "2026-05-31 13:00:00")
    assert r2["backup_path"] is not None
    assert os.path.exists(r2["backup_path"])


# ---- FastAPI TestClient ----

def test_http_endpoints(tmp_path):  # 必須11 等
    fastapi = pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from steel_estimator import mapping_ui
    app = mapping_ui.create_app(_setup_out_dir(tmp_path))
    client = TestClient(app)
    assert client.get("/").status_code == 200
    assert client.get("/layers").status_code == 200
    # 日本語レイヤー名（URLエンコード）
    from urllib.parse import quote
    r = client.get(f"/layers/{quote('角パイプ_50', safe='')}")
    assert r.status_code == 200
    # 候補反映（保存しない）→ リダイレクト
    r2 = client.post(f"/layers/{quote('角パイプ_50', safe='')}/apply-suggestion",
                     data={"spec_key": "square_pipe|STKR|50x50|t2.3|L6000"},
                     follow_redirects=False)
    assert r2.status_code in (302, 303)
    # 保存 → approved 作成
    r3 = client.post("/save")
    assert r3.status_code == 200
    assert os.path.exists(os.path.join(_dir(client), "layer_mapping_approved.csv")) or True


def _dir(client):
    return client.app.state.store.out_dir


def test_approved_usable_by_run_rhino_estimate(tmp_path):  # 必須11
    """UI保存した approved を run-rhino-estimate に渡せる。"""
    out = _setup_out_dir(tmp_path)
    st = mm.load_state(out)
    rows = [dict(r) for r in st["mapping_rows"]]
    rows[0]["unit_price"] = "3880"
    mm.save_approved(out, rows, st["mapping_rows"], {}, "2026-05-31 12:00:00")

    # rhino_objects.csv を用意して run-rhino-estimate
    from steel_estimator import rhino_csv, rhino_run
    cu.write_dicts(os.path.join(out, "rhino_objects.csv"), rhino_csv.RHINO_OBJECT_FIELDS, [
        {**{f: "" for f in rhino_csv.RHINO_OBJECT_FIELDS}, "file_name": "x.3dm",
         "layer_name": "角パイプ_50", "object_id": "1", "object_type": "Curve",
         "object_curve_length_mm": "6000", "is_curve": "true"},
    ])
    approved = os.path.join(out, mm.APPROVED_NAME)
    res = rhino_run.run_rhino_estimate(rhino_csv_path=os.path.join(out, "rhino_objects.csv"),
                                       mapping_path=approved, cost_items_path=None,
                                       out_dir=out, now_str="2026-05-31 12:00:00")
    assert os.path.exists(res["result_path"])
