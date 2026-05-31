"""公開用データ・匿名化・丸め・監査（Phase RC1.1）のテスト。"""

from steel_estimator import settings as tx
from steel_estimator import public_data as pub
from steel_estimator import cli
from steel_estimator import csv_utils as cu
from steel_estimator.models import MaterialCategory as C


# ---- 1: ceil_to_unit ----

def test_ceil_to_unit():  # 必須1
    assert tx.ceil_to_unit(273.5, 10) == 280
    assert tx.ceil_to_unit(270, 10) == 270
    assert tx.ceil_to_unit(295.5, 10) == 300
    assert tx.ceil_to_unit(706.7, 10) == 710
    assert tx.ceil_to_unit(866.7, 10) == 870
    assert tx.ceil_to_unit(5020, 10) == 5020
    assert tx.ceil_to_unit(5021, 10) == 5030


def test_public_price_order():  # 税抜丸め→税込再計算→丸め
    ex, inc = tx.public_price(270, 0.10, 10)
    assert ex == "270"
    assert inc == "300"   # ceil(270*1.1)=ceil(297)=300


# ---- range master 風の入力 ----

def _plate_range():
    return [
        {"material_grade": "SS400", "thickness_mm": "6", "plate_class": "rectangular_cut_plate",
         "sample_count": "3", "confidence": "0.4",
         "recommended_price_per_kg_ex_tax": "270", "conservative_price_per_kg_ex_tax": "272.6",
         "median_price_per_m2_ex_tax": "12000", "max_price_per_m2_ex_tax": "12500"},
        {"material_grade": "SS400", "thickness_mm": "6", "plate_class": "shaped_cut_plate",
         "sample_count": "59", "confidence": "0.4",
         "recommended_price_per_kg_ex_tax": "415.7", "conservative_price_per_kg_ex_tax": "3450",
         "median_price_per_m2_ex_tax": "19000", "max_price_per_m2_ex_tax": "90000"},
    ]


def _shape_range():
    return [
        {"material_category": C.SQUARE_PIPE, "material_grade": "SS400",
         "diameter_mm": "", "width_mm": "40", "height_mm": "40", "thickness_mm": "2.3",
         "stock_length_mm": "6000", "sample_count": "8", "confidence": "0.9",
         "recommended_unit_price_ex_tax": "4240", "conservative_unit_price_ex_tax": "4840",
         "recommended_price_per_m_ex_tax": "706.7", "conservative_price_per_m_ex_tax": "806.7",
         "recommended_price_per_kg_ex_tax": "259.5", "conservative_price_per_kg_ex_tax": "296"},
        {"material_category": C.ROUND_PIPE, "material_grade": "STK400",
         "diameter_mm": "48.6", "width_mm": "", "height_mm": "", "thickness_mm": "2.3",
         "stock_length_mm": "6000", "sample_count": "4", "confidence": "0.9",
         "recommended_unit_price_ex_tax": "4560", "conservative_unit_price_ex_tax": "4560",
         "recommended_price_per_m_ex_tax": "760", "conservative_price_per_m_ex_tax": "760",
         "recommended_price_per_kg_ex_tax": "300", "conservative_price_per_kg_ex_tax": "320"},
    ]


# ---- 2,3: 公開CSV生成 ----

def test_build_public_plate():  # 必須2
    rows = pub.build_public_plate(_plate_range(), tax_rate=0.10, unit=10)
    assert rows
    r = rows[0]
    # rectangular が代表に選ばれ、270→税込300
    assert r["recommended_price_per_kg_ex_tax_rounded"] == "270"
    assert r["recommended_price_per_kg_inc_tax_rounded"] == "300"
    assert r["thickness_mm"] == "6"


def test_build_public_shape():  # 必須3
    rows = pub.build_public_shape(_shape_range(), tax_rate=0.10, unit=10)
    sq = [r for r in rows if r["display_spec"] == "角パイプ 40x40 t2.3"][0]
    # 706.7 → 710 切り上げ
    assert sq["recommended_price_per_m_ex_tax_rounded"] == "710"
    assert sq["conservative_price_per_m_ex_tax_rounded"] == "810"


# ---- 4,5,6: 削除情報の不在 ----

def test_public_has_no_forbidden_columns():  # 必須4,5,6
    p = pub.build_public_plate(_plate_range(), 0.10, 10)[0]
    s = pub.build_public_shape(_shape_range(), 0.10, 10)[0]
    for forbidden in ("vendor_name", "quote_date", "latest_quote_date",
                      "source_pdf", "source_page", "spec_key", "amount", "quantity"):
        assert forbidden not in p
        assert forbidden not in s


# ---- 7,8: 帯表示 ----

def test_sample_count_band():  # 必須7
    assert pub.sample_count_band(1) == "1"
    assert pub.sample_count_band(3) == "2-5"
    assert pub.sample_count_band(10) == "6-20"
    assert pub.sample_count_band(99) == "21+"
    rows = pub.build_public_plate(_plate_range(), 0.10, 10)
    assert rows[0]["sample_count_band"] in ("1", "2-5", "6-20", "21+")


def test_confidence_band():  # 必須8
    assert pub.confidence_band(0.3) == "low"
    assert pub.confidence_band(0.5) == "medium"
    assert pub.confidence_band(0.9) == "high"


# ---- 9: 10円切り上げ ----

def test_public_values_rounded_to_10():  # 必須9
    rows = (pub.build_public_plate(_plate_range(), 0.10, 10)
            + pub.build_public_shape(_shape_range(), 0.10, 10))
    for r in rows:
        for k, v in r.items():
            if "rounded" in k and v:
                assert int(float(v)) % 10 == 0


# ---- 10: run-demo ----

def _write_public(tmp_path):
    pdir = tmp_path / "public_reference_data"
    pdir.mkdir()
    pub.write_public_plate(str(pdir / "public_plate_reference_prices.csv"),
                           pub.build_public_plate(_plate_range(), 0.10, 10))
    pub.write_public_shape(str(pdir / "public_shape_reference_prices.csv"),
                           pub.build_public_shape(_shape_range(), 0.10, 10))
    return pdir


def test_run_demo_completes(tmp_path):  # 必須10
    pdir = _write_public(tmp_path)
    out = tmp_path / "demo_out"
    rc = cli.main(["run-demo", "--out-dir", str(out),
                   "--public-dir", str(pdir), "--tax-rate", "0.10"])
    assert rc == 0
    assert (out / "what_costs_how_much.csv").exists()
    rows = cu.read_dicts(str(out / "what_costs_how_much.csv"))
    # 鉄板t6 が公開参考単価(270/kg税抜)で値付けされる
    plate = [r for r in rows if "鉄板" in r["item_name"]]
    assert plate and plate[0]["unit_price_ex_tax"] == "270"


# ---- 11: audit OK ----

def test_audit_public_ok(tmp_path):  # 必須11
    pdir = _write_public(tmp_path)
    # repo_root に安全な .gitignore を用意
    (tmp_path / ".gitignore").write_text(
        "data/\ncredentials.json\ntoken.json\n*.pdf\n", encoding="utf-8")
    rep = pub.audit_public_dir(str(pdir), repo_root=str(tmp_path))
    assert rep["ok"], rep["issues"]


def test_audit_detects_forbidden(tmp_path):
    pdir = tmp_path / "bad"
    pdir.mkdir()
    # vendor_name 列を含む不正CSV
    cu.write_dicts(str(pdir / "leak.csv"), ["vendor_name", "x"],
                   [{"vendor_name": "東鋼材", "x": "2025-01-01"}])
    (tmp_path / ".gitignore").write_text("data/\ncredentials.json\ntoken.json\n*.pdf\n",
                                         encoding="utf-8")
    rep = pub.audit_public_dir(str(pdir), repo_root=str(tmp_path))
    assert not rep["ok"]
    assert any("vendor_name" in i or "取引先" in i for i in rep["issues"])


# ---- 12: gitignore安全性 ----

def test_audit_git_safety_missing(tmp_path):  # 必須12
    pdir = _write_public(tmp_path)
    # data/ を除外しない .gitignore → issue
    (tmp_path / ".gitignore").write_text("credentials.json\n", encoding="utf-8")
    rep = pub.audit_public_dir(str(pdir), repo_root=str(tmp_path))
    assert not rep["ok"]
    assert any("data/" in i for i in rep["issues"])
