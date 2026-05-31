"""SQLite 保存層と CSV 入出力。"""

from __future__ import annotations

import csv
import hashlib
import os
import sqlite3
from typing import Iterable

from .models import MaterialRecord, MATERIAL_FIELDS


def _row_hash(rec: MaterialRecord) -> str:
    key = f"{rec.source_pdf_filename}|{rec.page_number}|{rec.raw_text_line}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


def connect(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _init_schema(conn)
    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    cols = ",\n  ".join(f"{f} {_sql_type(f)}" for f in MATERIAL_FIELDS)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS materials (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          row_hash TEXT UNIQUE,
          {cols}
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cat ON materials(material_category)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_grade ON materials(material_grade)")
    conn.commit()


def _sql_type(field: str) -> str:
    if field in ("page_number",):
        return "INTEGER"
    if field.endswith("_mm") or field in ("quantity", "unit_price", "amount", "confidence"):
        return "REAL"
    if field == "needs_review":
        return "INTEGER"
    return "TEXT"


def insert_records(conn: sqlite3.Connection, records: Iterable[MaterialRecord]) -> tuple[int, int]:
    """レコードを挿入。戻り: (inserted, skipped_duplicate)。"""
    inserted = skipped = 0
    placeholders = ",".join(["?"] * (len(MATERIAL_FIELDS) + 1))
    sql = f"INSERT OR IGNORE INTO materials (row_hash,{','.join(MATERIAL_FIELDS)}) VALUES ({placeholders})"
    for rec in records:
        d = rec.to_dict()
        d["needs_review"] = 1 if rec.needs_review else 0
        values = [_row_hash(rec)] + [d[f] for f in MATERIAL_FIELDS]
        cur = conn.execute(sql, values)
        if cur.rowcount:
            inserted += 1
        else:
            skipped += 1
    conn.commit()
    return inserted, skipped


def fetch_all(conn: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM materials")]


def fetch_by_category(conn: sqlite3.Connection, category: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM materials WHERE material_category=? AND unit_price IS NOT NULL",
        (category,),
    )
    return [dict(r) for r in rows]


def category_counts(conn: sqlite3.Connection) -> dict:
    rows = conn.execute(
        "SELECT material_category, COUNT(*) c FROM materials GROUP BY material_category ORDER BY c DESC"
    )
    return {r["material_category"]: r["c"] for r in rows}


# ============================================================
# CSV 入出力
# ============================================================

def write_records_csv(records: Iterable[MaterialRecord], out_path: str) -> int:
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    n = 0
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=MATERIAL_FIELDS)
        w.writeheader()
        for rec in records:
            d = rec.to_dict()
            d["needs_review"] = 1 if rec.needs_review else 0
            w.writerow(d)
            n += 1
    return n


def export_review_csv(conn: sqlite3.Connection, out_path: str) -> int:
    """needs_review を優先（先頭）に並べたレビュー用CSVを出力。"""
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM materials ORDER BY needs_review DESC, material_category, quote_date"
    )]
    fields = ["id", "row_hash"] + list(MATERIAL_FIELDS)
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return len(rows)
