"""設定値と消費税ユーティリティ（Phase R6.2）。

税の設計方針:
  - 内部計算は常に「税抜(ex_tax)」を基準にする。最後に税を加える。
  - 元データの税抜単価(unit_price 等)は破壊しない。税込は表示・標準値として併記する。
  - mapping(layer_mapping)の unit_price は税抜のまま保持し、二重課税を避ける。
  - tax_rate は初期値 0.10。CLIの --tax-rate で変更可能。

丸め:
  - 円未満は Python標準 round()（いわゆる偶数丸め/banker's rounding）で処理する。
  - 税抜が整数円のとき inc = ex + tax が厳密に成立する
    （round(N*(1+r)) == N + round(N*r), N が整数のため）。金額の整合が取れる。
  - 単価(円/kg 等)は小数を含みうるため、tax/inc は各々 ex から独立に算出して丸める。
"""

from __future__ import annotations

import math

DEFAULT_TAX_RATE = 0.10

# 公開用参考価格の丸め単位（円）。安全側に「切り上げ」。
DEFAULT_PUBLIC_ROUND_UNIT = 10


def _to_float(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(",", "").replace("，", "").strip()
    if s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _fmt(v) -> str:
    if v is None:
        return ""
    return f"{float(v):g}"


def normalize_rate(rate) -> float:
    """税率を float に正規化。None/空は DEFAULT_TAX_RATE。'10'→0.10 も許容。"""
    f = _to_float(rate)
    if f is None:
        return DEFAULT_TAX_RATE
    if f > 1.0:           # 10 のように%で渡された場合
        f = f / 100.0
    return f


def tax_of(ex, rate=DEFAULT_TAX_RATE):
    f = _to_float(ex)
    return None if f is None else round(f * normalize_rate(rate))


def inc_of(ex, rate=DEFAULT_TAX_RATE):
    f = _to_float(ex)
    return None if f is None else round(f * (1.0 + normalize_rate(rate)))


def triple(ex, rate=DEFAULT_TAX_RATE):
    """(ex_str, tax_str, inc_str) を返す。ex が空/非数なら ('','','')。"""
    f = _to_float(ex)
    if f is None:
        return ("", "", "")
    r = normalize_rate(rate)
    return (_fmt(f), _fmt(round(f * r)), _fmt(round(f * (1.0 + r))))


def tax_columns(prefix: str, ex, rate=DEFAULT_TAX_RATE) -> dict:
    """{prefix_ex_tax, prefix_tax, prefix_inc_tax} の dict を返す。"""
    ex_s, tax_s, inc_s = triple(ex, rate)
    return {
        f"{prefix}_ex_tax": ex_s,
        f"{prefix}_tax": tax_s,
        f"{prefix}_inc_tax": inc_s,
    }


def ceil_to_unit(value, unit: int = DEFAULT_PUBLIC_ROUND_UNIT):
    """value を unit 単位で切り上げる。None は None。

    例: ceil_to_unit(273.5)=280, ceil_to_unit(295.5)=300, ceil_to_unit(270)=270,
        ceil_to_unit(706.7)=710, ceil_to_unit(5021)=5030。
    浮動小数の誤差で 270.0→280 等にならないよう round(.,6) で吸収する。
    """
    f = _to_float(value)
    if f is None:
        return None
    return int(math.ceil(round(f / unit, 6)) * unit)


def public_price(ex, rate=DEFAULT_TAX_RATE, unit: int = DEFAULT_PUBLIC_ROUND_UNIT):
    """公開用の (税抜丸め, 税込丸め) を返す。

    計算順（安全側）:
      1) 税抜を unit 単位で切り上げ → ex_rounded
      2) 税込 = ex_rounded × (1+税率) を unit 単位で切り上げ
    """
    exr = ceil_to_unit(ex, unit)
    if exr is None:
        return ("", "")
    incr = ceil_to_unit(exr * (1.0 + normalize_rate(rate)), unit)
    return (str(exr), str(incr))


def tax_view(ex, rate=DEFAULT_TAX_RATE) -> dict:
    """UI表示用。{'ex':float|None,'tax':int|None,'inc':int|None,'rate':float}。"""
    f = _to_float(ex)
    r = normalize_rate(rate)
    if f is None:
        return {"ex": None, "tax": None, "inc": None, "rate": r}
    return {"ex": f, "tax": round(f * r), "inc": round(f * (1.0 + r)), "rate": r}
