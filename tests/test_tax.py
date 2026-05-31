"""消費税対応（Phase R6.2）のテスト。

方針: 内部計算は税抜基準。unit_price は税抜。*_inc_tax が税込標準値。二重課税しない。
"""

from steel_estimator import settings as tx
from steel_estimator import price_analysis as pa
from steel_estimator import layer_estimate as lest
from steel_estimator import enrich
from steel_estimator import candidate_prices as cp
from steel_estimator import layer_mapping as lmap
from steel_estimator import mapping_ui_models as ui
from steel_estimator.models import MaterialCategory as C


def summ(**kw):
    base = {f: "" for f in cp.SUMMARY_FIELDS}
    base["sample_count"] = 3
    base["usable_as_base_price"] = "true"
    base["candidate_class"] = cp.CLASS_BASE
    base.update(kw)
    return base


def mrow(**kw):
    base = {f: "" for f in lmap.MAPPING_FIELDS}
    base["enabled"] = "true"
    base["waste_rate"] = "1.0"
    base.update(kw)
    return base


# ---- 1, 2: 税率と換算 ----

def test_inc_270_to_297_at_10pct():  # 必須1
    assert tx.inc_of(270, 0.10) == 297
    assert tx.tax_of(270, 0.10) == 27
    ex, tax, inc = tx.triple(270, 0.10)
    assert (ex, tax, inc) == ("270", "27", "297")


def test_rate_change_8pct():  # 必須2
    assert tx.inc_of(270, 0.10) == 297
    assert tx.inc_of(270, 0.08) == 292   # round(291.6)
    assert tx.inc_of(270, 0.10) != tx.inc_of(270, 0.08)


def test_normalize_rate_percent_form():
    assert tx.normalize_rate(10) == 0.10
    assert tx.normalize_rate(None) == tx.DEFAULT_TAX_RATE


# ---- 3: practical_price_master 税込カラム ----

def test_practical_master_has_tax_columns():  # 必須3
    s = summ(material_category=C.SQUARE_PIPE, material_grade="STKR",
             spec_key="square_pipe|STKR|50x50|t2.3|L6000",
             latest_unit_price="5020", median_unit_price="4900",
             average_unit_price="4950", price_unit="個")
    row = pa.build_practical_master([s], tax_rate=0.10)[0]
    assert "price_per_kg_inc_tax" in row
    assert row["tax_rate"] == 0.10
    assert row["latest_unit_price_ex_tax"] == "5020"
    assert row["latest_unit_price_inc_tax"] == "5522"   # round(5020*1.1)


# ---- 4: plate_reference_price 税込カラム ----

def test_plate_reference_has_tax_columns():  # 必須4
    rows = pa.build_plate_reference([{
        **{f: "" for f in cp.CANDIDATE_FIELDS},
        "material_category": C.PLATE, "material_grade": "SS400",
        "spec_key": "plate|SS400|t6|300x300", "spec_text": "切板",
        "quantity": "6", "unit_price": "720", "amount": "4320",
    }], tax_rate=0.10)
    r = rows[0]
    assert "price_per_kg_inc_tax" in r
    assert r["tax_rate"] == 0.10
    assert r["unit_price_inc_tax"] == "792"   # round(720*1.1)


# ---- 5: plate_reference_summary_by_thickness 税込カラム + SS400 t6 270→297 ----

def test_plate_summary_tax_columns_270_to_297():  # 必須5
    refs = [{
        "material_grade": "SS400", "thickness_mm": "6", "plate_class": "rectangular_cut_plate",
        "price_per_kg": "270", "price_per_m2": "12000", "quote_date": "2025-06-26",
        "usable_as_reference": "true",
    }]
    s = pa.build_plate_reference_summary(refs, tax_rate=0.10)[0]
    assert s["median_price_per_kg"] == "270"
    assert s["median_price_per_kg_inc_tax"] == "297"   # 税込標準値
    assert s["tax_rate"] == 0.10


def test_practical_master_plate_reference_inc():  # 必須9相当(master側のplate_reference)
    refs = [{
        "material_grade": "SS400", "thickness_mm": "6", "plate_class": "rectangular_cut_plate",
        "price_per_kg": "270", "price_per_m2": "12000", "quote_date": "2025-06-26",
        "usable_as_reference": "true",
    }]
    summ_rows = pa.build_plate_reference_summary(refs, tax_rate=0.10)
    master = pa.build_practical_master([], summ_rows, tax_rate=0.10)
    pref = [m for m in master if m["candidate_class"] == "plate_reference"][0]
    assert pref["price_per_kg"] == "270"
    assert pref["price_per_kg_inc_tax"] == "297"
    assert pref["usable_as_base_price"] == "false"


# ---- 6, 11: enrich の unit_price は税抜のまま（二重課税なし） ----

MASTER = pa.build_practical_master([
    summ(material_category=C.SQUARE_PIPE, material_grade="STKR",
         spec_key="square_pipe|STKR|50x50|t2.3|L6000",
         latest_unit_price="5020", latest_quote_date="2025-11-12",
         price_unit="個", vendor_name="東鋼材", confidence="0.9", needs_review="false"),
], tax_rate=0.10)


def test_enrich_unit_price_stays_ex_tax():  # 必須6, 11
    rows = mrow(layer_name="架台::角パイプ_50", material_category=C.SQUARE_PIPE,
                width_mm="50", height_mm="50", thickness_mm="2.3")
    out = enrich.enrich_mapping([rows], [], MASTER, tax_rate=0.10)[0]
    if out["unit_price"]:
        ex = float(out["unit_price"])
        # 税込(5522)が入っていないこと＝二重課税していない
        assert ex == 5020.0
        # 税込は notes に参考表示
        assert "税込参考" in out["notes"]


# ---- 7, 8: estimate_result / estimate_summary 税対応 ----

def _fixed_results(amount=10000, rate=0.10):
    m = [mrow(layer_name="固定費", calc_type=lmap.CALC_FIXED_AMOUNT, fixed_amount=str(amount))]
    results, summary = lest.estimate_layers([], m, tax_rate=rate)
    return results, summary


def test_estimate_result_tax_columns():  # 必須7
    results, _ = _fixed_results(10000, 0.10)
    r = next(r for r in results if r.get("estimated_amount") == 10000)
    assert r["estimated_amount_ex_tax"] == "10000"
    assert r["estimated_tax_amount"] == "1000"
    assert r["estimated_amount_inc_tax"] == "11000"
    assert r["tax_rate"] == 0.10


def test_estimate_summary_total_tax():  # 必須8
    _, summary = _fixed_results(10000, 0.10)
    total = next(s for s in summary if str(s["category"]).startswith("TOTAL"))
    assert total["subtotal_amount_ex_tax"] == 10000
    assert total["tax_amount"] == 1000
    assert total["subtotal_amount_inc_tax"] == 11000
    # 二重課税なし: ex + tax == inc
    assert total["subtotal_amount_ex_tax"] + total["tax_amount"] == total["subtotal_amount_inc_tax"]


# ---- 9: what_costs_how_much 税込 ----

def test_what_costs_has_inc_tax():  # 必須9
    results, _ = _fixed_results(10000, 0.10)
    rows = lest.build_what_costs(results, 0.10)
    assert rows
    r = rows[0]
    assert r["estimated_amount_ex_tax"] == "10000"
    assert r["estimated_amount_inc_tax"] == "11000"
    assert r["estimated_tax_amount"] == "1000"


# ---- 10: mapping-ui 税込表示用データ ----

def test_ui_price_tax_view():  # 必須10
    v = ui.price_tax_view(270, 0.10)
    assert v["ex"] == 270 and v["tax"] == 27 and v["inc"] == 297
    assert v["rate"] == 0.10


def test_ui_dashboard_tax_fields():  # 必須10
    state = {
        "mapping_rows": [],
        "suggestions_by_layer": {},
        "summary_by_layer": {},
        "estimate_summary": [
            {"category": "TOTAL(除ignored)", "subtotal_amount": 10000,
             "subtotal_amount_ex_tax": 10000, "tax_amount": 1000,
             "subtotal_amount_inc_tax": 11000},
        ],
    }
    d = ui.dashboard_data(state, 0.10)
    assert d["tax_rate"] == 0.10
    assert str(d["estimate_total_inc_tax"]) == "11000"
