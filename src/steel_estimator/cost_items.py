"""加工費・運搬費など、Rhinoレイヤーとは別に見積へ追加する費目（cost_items.csv）。

生材単価とは分離して扱う（曲げ・型切・溶接などの加工費を材料費に混ぜない原則）。
"""

from __future__ import annotations

from . import csv_utils as cu


COST_ITEM_FIELDS = (
    "item_name",
    "cost_category",
    "calc_type",     # fixed_amount または quantity（quantity×unit_price）
    "quantity",
    "unit",
    "unit_price",
    "fixed_amount",
    "notes",
)

# cost_category → estimate_summary のカテゴリ
COST_CATEGORY_TO_SUMMARY = {
    "cutting": "processing",
    "bending": "processing",
    "welding": "processing",
    "drilling": "processing",
    "painting": "processing",
    "transport": "transport",
    "installation": "installation",
    "design": "design",
    "subcontract": "processing",
    "other": "unknown",
}


def read_cost_items(path: str) -> list[dict]:
    rows = cu.read_dicts(path)
    for r in rows:
        for f in COST_ITEM_FIELDS:
            r.setdefault(f, "")
    return rows


def summary_category(cost_category: str) -> str:
    return COST_CATEGORY_TO_SUMMARY.get((cost_category or "").strip().lower(), "processing")
