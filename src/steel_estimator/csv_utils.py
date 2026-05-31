"""CSV入出力ユーティリティ。

Excel互換のため書き出しは UTF-8 with BOM（utf-8-sig）。
読み込みも utf-8-sig を使い、BOM有無どちらも透過的に扱う。
"""

from __future__ import annotations

import csv
import os
from typing import Iterable, Optional


def read_dicts(path: str) -> list[dict]:
    """CSVを dict のリストとして読む。BOM有無どちらも可。キー/値は前後空白を除去。"""
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = []
        for row in reader:
            clean = {}
            for k, v in row.items():
                if k is None:
                    continue
                clean[k.strip()] = (v.strip() if isinstance(v, str) else v)
            rows.append(clean)
        return rows


def write_dicts(path: str, fieldnames: Iterable[str], rows: Iterable[dict]) -> int:
    """dict 群を UTF-8 with BOM で書き出す。未知キーは無視、欠損は空欄。"""
    fieldnames = list(fieldnames)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    n = 0
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: _cell(r.get(k, "")) for k in fieldnames})
            n += 1
    return n


def _cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        # 整数値は整数表記（5500.0 → 5500）
        return f"{v:g}"
    return str(v)


def to_float(s) -> Optional[float]:
    if s is None:
        return None
    s = str(s).replace(",", "").replace("，", "").strip()
    s = s.translate(str.maketrans("０１２３４５６７８９．", "0123456789."))
    if s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def to_int(s) -> Optional[int]:
    v = to_float(s)
    return int(v) if v is not None else None


def to_bool(s, default: bool = True) -> bool:
    """'true/1/yes/y/有効' → True, 'false/0/no/n/無効' → False。空欄は default。"""
    if s is None:
        return default
    t = str(s).strip().lower()
    if t == "":
        return default
    if t in ("true", "1", "yes", "y", "有効", "on"):
        return True
    if t in ("false", "0", "no", "n", "無効", "off"):
        return False
    return default
