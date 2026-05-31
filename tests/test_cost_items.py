"""cost_items の合算と総括カテゴリのテスト。"""

import pytest

from steel_estimator import layer_mapping as lmap
from steel_estimator import layer_estimate as lest


def mrow(**kw):
    base = {f: "" for f in lmap.MAPPING_FIELDS}
    base["enabled"] = "true"
    base["waste_rate"] = "1.0"
    base.update(kw)
    return base


COST_ROWS = [
    {"item_name": "レーザー切断", "cost_category": "cutting", "calc_type": "fixed_amount",
     "quantity": "", "unit": "", "unit_price": "", "fixed_amount": "12000", "notes": ""},
    {"item_name": "溶接組立", "cost_category": "welding", "calc_type": "quantity",
     "quantity": "8", "unit": "箇所", "unit_price": "2500", "fixed_amount": "", "notes": ""},
    {"item_name": "現場取付", "cost_category": "installation", "calc_type": "fixed_amount",
     "quantity": "", "unit": "", "unit_price": "", "fixed_amount": "30000", "notes": ""},
    {"item_name": "運搬", "cost_category": "transport", "calc_type": "fixed_amount",
     "quantity": "", "unit": "", "unit_price": "", "fixed_amount": "18000", "notes": ""},
]


def test_cost_items_merged_into_estimate():  # 必須17
    summary = [{"layer_name": "鉄板", "total_area_m2": "2.0", "object_count": "",
                "total_volume_mm3": "", "total_curve_length_m": ""}]
    mapping = [mrow(layer_name="鉄板", calc_type="area_to_weight", thickness_mm="6",
                    density_g_cm3="7.85", unit_price="150", price_unit="kg")]
    results, summ = lest.estimate_layers(summary, mapping, cost_rows=COST_ROWS)

    cost_results = [r for r in results if r["source_type"] == "cost_item"]
    assert len(cost_results) == 4
    weld = [r for r in cost_results if r["item_name"] == "溶接組立"][0]
    assert weld["estimated_amount"] == pytest.approx(20000)  # 8×2500
    cut = [r for r in cost_results if r["item_name"] == "レーザー切断"][0]
    assert cut["estimated_amount"] == pytest.approx(12000)


def test_cost_category_summary_buckets():  # 必須18の補完
    summary = []
    mapping = []
    _, summ = lest.estimate_layers(summary, mapping, cost_rows=COST_ROWS)
    by = {r["category"]: r for r in summ}
    # cutting/welding → processing, installation→installation, transport→transport
    assert by["processing"]["subtotal_amount"] == pytest.approx(32000)  # 12000+20000
    assert by["installation"]["subtotal_amount"] == pytest.approx(30000)
    assert by["transport"]["subtotal_amount"] == pytest.approx(18000)


def test_cost_item_missing_price_needs_review():
    bad = [{"item_name": "謎費目", "cost_category": "other", "calc_type": "quantity",
            "quantity": "", "unit": "", "unit_price": "", "fixed_amount": "", "notes": ""}]
    results, _ = lest.estimate_layers([], [], cost_rows=bad)
    assert results[0]["needs_review"] == "true"
