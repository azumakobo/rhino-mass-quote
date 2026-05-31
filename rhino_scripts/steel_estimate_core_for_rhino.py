# -*- coding: utf-8 -*-
"""Rhino内UI用の軽量見積ロジック（Rhino非依存・標準ライブラリのみ・自己完結）。

Rhino の Python から steel_estimator パッケージを import できるとは限らないため、
このモジュールは外部依存なしで完結する（csv/re/math のみ）。pytest でも単体検証できる。

標準方針(2026-05-31〜): 鋼材はポリサーフェス → 体積→重量(volume_to_weight)。
価格は public_reference_data の公開用参考価格（実取引価格ではない）を使う。
"""

import csv
import io
import math
import os
import re

# 依存core取り違え/古いキャッシュ検出用のバージョン
CORE_VERSION = "steel-estimate-core-quote-factor-2026-05-31"

DEFAULT_TAX_RATE = 0.10

# 密度 g/cm3
DENSITY_STEEL = 7.85
DENSITY_SUS304 = 7.93
DENSITY_ALUMINUM = 2.70

# レイヤー名 ASCII コード → カテゴリ
_CODE_CAT = {
    "PL": "plate", "PLATE": "plate",
    "SQPIPE": "square_pipe", "SQ": "square_pipe",
    "PIPE": "round_pipe", "RPIPE": "round_pipe",
    "ANGLE": "angle", "FB": "flat_bar",
    "CH": "channel", "CHANNEL": "channel",
    "RBAR": "round_bar", "SBAR": "square_bar", "HBEAM": "h_beam",
}
_CODE_SPECIAL = {"BOLT": "object_count", "NUT": "object_count", "SCREW": "object_count",
                 "IGNORE": "ignore", "GUIDE": "ignore"}
_STEEL_CATS = ("square_pipe", "round_pipe", "angle", "flat_bar",
               "round_bar", "square_bar", "h_beam", "channel")

_IGNORE_HINTS = ("補助線", "補助", "注釈", "検討", "ガイド", "通り芯", "IGNORE", "GUIDE")
_COUNT_HINTS = ("ボルト", "ナット", "金物", "BOLT", "NUT")
_PLATE_HINTS = ("鉄板", "鋼板", "プレート", "PL", "PLATE", "板")
_STEEL_HINTS = ("角パイプ", "丸パイプ", "アングル", "フラットバー", "平鋼", "丸棒",
                "SQPIPE", "PIPE", "ANGLE", "FB", "STEEL", "METAL")

_GRADE_RE = re.compile(
    r"(SUS\s?316L?|SUS\s?304|STKMR?\d*|STKR\d*|STK\d*|SGP|SS400|S\d{2}C|A\d{4}|AL)",
    re.IGNORECASE)
_PHI_RE = re.compile(r"[φΦ]\s?(\d+(?:\.\d+)?)")
_DIA_D_RE = re.compile(r"(?:^|[_\s\-])D(\d+(?:\.\d+)?)")
_T_RE = re.compile(r"(?:板厚|厚|t)\s?(\d+(?:\.\d+)?)", re.IGNORECASE)
_PAIR_RE = re.compile(r"(\d+(?:\.\d+)?)\s?[x×X*]\s?(\d+(?:\.\d+)?)")


# ============================================================
# 推定
# ============================================================

def _code(name):
    if not name:
        return ""
    return (name.split("_", 1)[0] if "_" in name else name).strip().upper()


def infer_category(name):
    """レイヤー名からカテゴリ（または ignore/object_count 用の特例カテゴリ）。"""
    code = _code(name)
    if code in _CODE_CAT:
        return _CODE_CAT[code]
    up = (name or "").upper()
    if any(h.upper() in up for h in _IGNORE_HINTS):
        return "ignore"
    if any(h.upper() in up for h in _COUNT_HINTS):
        return "object_count"
    if any(h.upper() in up for h in _STEEL_HINTS):
        # 種別名でカテゴリを細分
        for code_key, cat in _CODE_CAT.items():
            if code_key in up:
                return cat
        return "square_pipe" if "SQ" in up else "round_pipe" if "PIPE" in up else "steel"
    if any(h.upper() in up for h in _PLATE_HINTS):
        return "plate"
    return "unknown"


def infer_grade(name):
    m = _GRADE_RE.search(name or "")
    if not m:
        return ""
    g = m.group(1).upper().replace(" ", "")
    return "AL" if g == "AL" else g


def infer_dims(name):
    out = {"thickness_mm": None, "diameter_mm": None, "width_mm": None, "height_mm": None}
    if not name:
        return out
    phi = _PHI_RE.search(name) or _DIA_D_RE.search(name)
    if phi:
        out["diameter_mm"] = float(phi.group(1))
    pair = _PAIR_RE.search(name)
    if pair:
        out["width_mm"] = float(pair.group(1))
        out["height_mm"] = float(pair.group(2))
    tm = _T_RE.search(name)
    if tm:
        out["thickness_mm"] = float(tm.group(1))
    return out


def density_for_grade(grade):
    """(密度 g/cm3, warning)。"""
    g = (grade or "").upper()
    if "SUS304" in g or "SUS316" in g:
        return DENSITY_SUS304, ""
    if g == "AL" or re.match(r"A\d{4}", g) or "ALUMIN" in g:
        return DENSITY_ALUMINUM, ""
    if any(k in g for k in ("SS400", "STK", "STKR", "SGP", "STKM", "S45C", "STEEL")):
        return DENSITY_STEEL, ""
    return DENSITY_STEEL, "材質不明: 密度7.85(鉄)を仮定"


# ============================================================
# 公開参考価格の読み込み・kg単価検索
# ============================================================

def _read_csv(path):
    if not path or not os.path.exists(path):
        return []
    with io.open(path, newline="", encoding="utf-8-sig") as f:
        return [{(k.strip() if k else k): (v.strip() if isinstance(v, str) else v)
                 for k, v in row.items()} for row in csv.DictReader(f)]


def _f(v):
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _g(v):
    """数値を簡潔な文字列に（48.6→'48.6', 6000.0→'6000'）。None→''。"""
    if v is None or v == "":
        return ""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return ("%g" % f)


def load_reference(public_dir=None, plate_path=None, shape_path=None):
    """公開参考価格を読み込む。{'plate':[...], 'shape':[...]}。"""
    pdir = public_dir or "."
    plate = plate_path or os.path.join(pdir, "public_plate_reference_prices.csv")
    shape = shape_path or os.path.join(pdir, "public_shape_reference_prices.csv")
    return {"plate": _read_csv(plate), "shape": _read_csv(shape)}


def _kg_field(mode):
    return ("conservative_price_per_kg_ex_tax_rounded" if mode == "conservative"
            else "recommended_price_per_kg_ex_tax_rounded")


_REC_KG = "recommended_price_per_kg_ex_tax_rounded"
_CON_KG = "conservative_price_per_kg_ex_tax_rounded"


def _median(vals):
    vals = sorted(v for v in vals if v is not None)
    if not vals:
        return None
    n = len(vals)
    return vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2.0


def lookup_shape_kg_price(category, grade, dims, shape_rows):
    """形鋼の (recommended_per_kg_ex, conservative_per_kg_ex, source, warning)。

    優先: 寸法一致のkg単価 → 同カテゴリ(同材質優先)の代表kg単価(fallback)。
    kg単価が公開参考に無いカテゴリ(angle/h_beam/square_bar)は None+warning。
    """
    cands = [r for r in shape_rows if r.get("material_category") == category]
    if not cands:
        return None, None, "", "公開参考に同カテゴリなし"

    # 1) 寸法一致
    best, best_score = None, -1
    for r in cands:
        score, ok = 0, True
        for k in ("diameter_mm", "width_mm", "height_mm", "thickness_mm"):
            mv, rv = dims.get(k), _f(r.get(k))
            if mv is not None and rv is not None:
                if abs(mv - rv) <= 0.01:
                    score += 1
                else:
                    ok = False
                    break
        if ok and score > best_score:
            best, best_score = r, score
    if best is not None and best_score >= 1 and _f(best.get(_REC_KG)) is not None:
        return _f(best.get(_REC_KG)), _f(best.get(_CON_KG)), "public_shape", ""

    # 2) 同カテゴリ代表（同材質優先）の fallback
    g = (grade or "").upper()
    pool = [r for r in cands if g and r.get("material_grade", "").upper() == g] or cands
    recs = [_f(r.get(_REC_KG)) for r in pool]
    if any(v is not None for v in recs):
        cons = [_f(r.get(_CON_KG)) for r in pool]
        return (_median(recs), _median(cons), "public_shape_category_fallback",
                "カテゴリfallback単価を使用(寸法一致なし)")
    return None, None, "", "公開参考にkg単価なし(JIS重量表が必要なカテゴリ)"


def lookup_plate_kg_price(grade, thickness_mm, plate_rows):
    """板材の kg単価。板厚一致 → 同材質/全体の代表kg単価(fallback)。"""
    if not plate_rows:
        return None, None, "", "公開参考に板材なし"
    g = (grade or "").upper()
    exact = [r for r in plate_rows if thickness_mm is not None
             and _f(r.get("thickness_mm")) == thickness_mm]
    if exact:
        exact.sort(key=lambda r: 0 if (g and r.get("material_grade", "").upper() == g) else 1)
        b = exact[0]
        return _f(b.get(_REC_KG)), _f(b.get(_CON_KG)), "public_plate", ""
    pool = [r for r in plate_rows if g and r.get("material_grade", "").upper() == g] or plate_rows
    recs = [_f(r.get(_REC_KG)) for r in pool]
    if any(v is not None for v in recs):
        cons = [_f(r.get(_CON_KG)) for r in pool]
        return (_median(recs), _median(cons), "public_plate_category_fallback",
                "カテゴリfallback単価を使用(板厚一致なし)")
    return None, None, "", "公開参考にkg単価なし"


# ============================================================
# 計算
# ============================================================

def weight_from_volume(volume_mm3, density):
    return volume_mm3 * density * 1e-6


def weight_from_area(area_m2, thickness_mm, density):
    # area_m2 × (t_mm/1000)m = 体積m3、×density(g/cm3=1000kg/m3)×1000 = kg
    return area_m2 * thickness_mm * density


def decide_calc_type(category, volume_mm3, area_m2):
    """簡素化方針(2026-05-31): volume があれば形状に関係なく volume_to_weight。

    断面形状の再現は不要。レイヤー内の volume 合計をそのまま正とする
    （Box でも Cylinder でも、Rhinoが返す体積を信頼する）。
    """
    if category == "ignore":
        return "ignore"
    # 1) volume が取れれば全カテゴリ volume_to_weight（PL含む）
    if volume_mm3 and volume_mm3 > 0:
        return "volume_to_weight"
    # 2) volume無し・PLでareaあり → area_to_weight（fallback）
    if category == "plate" and area_m2 and area_m2 > 0:
        return "area_to_weight"
    # 3) volume も area も無い
    if category == "object_count":
        return "object_count"
    return "needs_review"


def estimate_layer(agg, ref, tax_rate=DEFAULT_TAX_RATE, pricing_mode="median"):
    """1レイヤー集計 agg から見積行 dict を作る。

    agg: {layer_name, volume_mm3, area_m2, object_count}
    """
    name = agg.get("layer_name", "")
    volume = _f(agg.get("volume_mm3")) or 0.0
    area = _f(agg.get("area_m2")) or 0.0
    count = int(_f(agg.get("object_count")) or 0)
    category = infer_category(name)
    grade = infer_grade(name)
    dims = infer_dims(name)
    calc = decide_calc_type(category, volume, area)
    density, dwarn = density_for_grade(grade)

    row = {
        "layer_name": name, "category": category, "calc_type": calc,
        "object_count": count,
        "material_grade": grade, "density_g_cm3": density,
        "volume_mm3": round(volume, 1) if volume else "",
        "area_m2": round(area, 4) if area else "",
        "weight_kg": "", "unit_price_ex_tax": "", "unit_price_inc_tax": "",
        "price_unit": "", "amount_ex_tax": "", "amount_inc_tax": "",
        "recommended_amount_ex_tax": "", "conservative_amount_ex_tax": "",
        "pricing_mode": pricing_mode, "warning": "",
    }
    warns = []

    if calc == "ignore":
        row["warning"] = "対象外(ignore)"
        return row
    if calc == "object_count":
        row["warning"] = "購入部品: 個数×単価は手入力(UI後続/CLI)"
        row["price_unit"] = "個"
        return row
    if calc == "needs_review":
        row["warning"] = "体積/面積が取れず見積不能。閉じたポリサーフェス/面で作図を"
        return row

    # 重量
    if calc == "volume_to_weight":
        weight = weight_from_volume(volume, density)
    else:  # area_to_weight
        t = dims.get("thickness_mm")
        if t is None:
            row["warning"] = "板厚不明(レイヤー名にt6等)・重量計算不可"
            return row
        weight = weight_from_area(area, t, density)
    if dwarn:
        warns.append(dwarn)
    row["weight_kg"] = round(weight, 3)

    # kg単価
    if category == "plate":
        rec, con, src, pwarn = lookup_plate_kg_price(grade, dims.get("thickness_mm"), ref.get("plate", []))
    else:
        rec, con, src, pwarn = lookup_shape_kg_price(category, grade, dims, ref.get("shape", []))
    if pwarn:
        warns.append(pwarn)
    row["price_unit"] = "kg"
    if rec is None:
        warns.append("kg単価未確定: mapping UI等で手入力")
        row["warning"] = "; ".join(warns)
        return row

    selected = con if pricing_mode == "conservative" else rec
    row["unit_price_ex_tax"] = selected
    row["unit_price_inc_tax"] = _round_tax(selected, tax_rate, inc=True)
    row["amount_ex_tax"] = round(weight * selected, 1)
    row["amount_inc_tax"] = _round_tax(row["amount_ex_tax"], tax_rate, inc=True)
    row["recommended_amount_ex_tax"] = round(weight * rec, 1)
    row["conservative_amount_ex_tax"] = round(weight * con, 1) if con is not None else row["recommended_amount_ex_tax"]
    row["warning"] = "; ".join(warns)
    return row


def estimate_all(aggregates, ref, tax_rate=DEFAULT_TAX_RATE, pricing_mode="median"):
    """全レイヤーの行と合計を返す。"""
    rows = [estimate_layer(a, ref, tax_rate, pricing_mode) for a in aggregates]
    totals = compute_totals(rows, tax_rate)
    return rows, totals


def compute_totals(rows, tax_rate=DEFAULT_TAX_RATE):
    # 合計は整数円に丸めてから課税（ex + tax == inc を厳密に成立させる）
    def _sum(key):
        return int(round(sum(_f(r.get(key)) or 0.0 for r in rows)))
    ex = _sum("amount_ex_tax")
    rec = _sum("recommended_amount_ex_tax")
    con = _sum("conservative_amount_ex_tax")
    tax = int(round(ex * tax_rate))
    return {
        "subtotal_ex_tax": ex,
        "tax_amount": tax,
        "subtotal_inc_tax": ex + tax,
        "recommended_ex_tax": rec,
        "recommended_inc_tax": rec + int(round(rec * tax_rate)),
        "conservative_ex_tax": con,
        "conservative_inc_tax": con + int(round(con * tax_rate)),
        "tax_rate": tax_rate,
    }


def _round_tax(value_ex, tax_rate, inc=True):
    if value_ex in (None, ""):
        return ""
    v = float(value_ex)
    return round(v * (1 + tax_rate)) if inc else round(v * tax_rate)


# ============================================================
# CSV出力
# ============================================================

# mass中心の列順（volume/weight/単価/金額を中心に。area等は補助）
CSV_COLUMNS = [
    "layer_name", "category", "calc_type", "object_count",
    "volume_mm3", "area_m2", "material_grade", "density_g_cm3", "weight_kg",
    "unit_price_ex_tax", "unit_price_inc_tax", "price_unit",
    "amount_ex_tax", "amount_inc_tax", "pricing_mode", "warning",
]


def write_csv(path, rows):
    """UTF-8 with BOM で見積結果を書き出す。"""
    folder = os.path.dirname(os.path.abspath(path))
    if folder and not os.path.isdir(folder):
        os.makedirs(folder, exist_ok=True)
    with io.open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in CSV_COLUMNS})
    return path


def resolve_output_path(model_path=None):
    """CSV出力先: モデルと同じフォルダ、無ければDesktop。"""
    if model_path and os.path.isdir(os.path.dirname(model_path)):
        return os.path.join(os.path.dirname(model_path), "steel_estimate_result.csv")
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    if not os.path.isdir(desktop):
        desktop = os.path.expanduser("~")
    return os.path.join(desktop, "steel_estimate_result.csv")


# ============================================================
# 重量計算用素材（密度）と 概算用単価カテゴリ（円/kg）の分離
# ============================================================
# 重要: 「重量計算用素材」は密度を決めるだけ。「概算用単価カテゴリ」は公開参考価格の
# 円/kg を決める。両者は別物（連動してもよいが同一ではない）。

import json as _json

# Quote の重量計算用素材は金属見積用に **3択**（内部値 steel/stainless/aluminum）。
# 細かい規格(SS400/STK/STKR/SUS304/A5052…)は次画面「概算用単価カテゴリ」で選ぶ。
DENSITY_MATERIALS = [
    ("steel", 7.85), ("stainless", 7.93), ("aluminum", 2.70),
]
DENSITY_BY_MATERIAL = {k: v for k, v in DENSITY_MATERIALS}

_JP_CAT = {"plate": "板", "square_pipe": "角パイプ", "round_pipe": "丸パイプ",
           "flat_bar": "FB", "round_bar": "丸棒", "angle": "アングル",
           "square_bar": "角棒", "h_beam": "H形鋼", "channel": "チャンネル"}

# 重量計算用素材（内部値→日本語表示）。内部値は英語のまま、UI表示だけ日本語化する。
DENSITY_MATERIAL_LABELS = {
    "steel": "鉄（SS400 / STK / STKR）",
    "stainless": "ステンレス（SUS304）",
    "aluminum": "アルミ（A5052）",
}
# pricing_mode（内部値→日本語表示）
PRICING_MODE_LABELS = {
    "recommended": "通常見積（中央値）",
    "conservative": "安全側見積（最大値）",
    "manual": "手入力",
}


def material_label(material):
    return DENSITY_MATERIAL_LABELS.get(material, material)


def pricing_mode_label(mode):
    return PRICING_MODE_LABELS.get(mode, mode)


# Quote 安全係数: 公開参考価格(通常/安全側)に掛ける。manual・Mass・元CSVには適用しない。
# 「安全側見積が実見積より安く出る」リスクを避けるため高め(×1.2)に補正する。
QUOTE_PRICE_FACTOR = 1.2


def _ceil10(v):
    """10円単位に切り上げ。None は None。"""
    if v is None:
        return None
    return int(math.ceil(float(v) / 10.0) * 10)


def apply_quote_factor(price, factor=None):
    """公開参考kg単価に安全係数を掛け、10円単位切り上げ。None は None。"""
    if price is None:
        return None
    f = QUOTE_PRICE_FACTOR if factor is None else factor
    return _ceil10(float(price) * f)


def density_for_material(material, custom_value=None):
    """Quote 重量計算用素材(steel/stainless/aluminum)→密度 g/cm3。"""
    d = DENSITY_BY_MATERIAL.get(material)
    return d if d is not None else (_f(custom_value) if custom_value is not None else DENSITY_STEEL)


def map_grade_to_quote_material(name):
    """規格名・レイヤー名・材質を Quote の3素材(steel/stainless/aluminum)へ写像。

    SS400/STK/STKR/Steel→steel、SUS304/SUS/Stainless→stainless、
    A5052/Aluminum/AL→aluminum。判別不能は steel。
    """
    s = (name or "").upper()
    if any(k in s for k in ("SUS304", "SUS316", "SUS", "STAINLESS")):
        return "stainless"
    if "A5052" in s or "ALUMIN" in s or re.search(r"A\d{4}", s) or s.strip() == "AL":
        return "aluminum"
    return "steel"


def build_price_catalog(ref):
    """公開参考価格CSVから「概算用単価カテゴリ」の選択肢を作る。

    各要素: {key, label, category, material_grade, recommended_per_kg, conservative_per_kg}
    """
    out = []
    for r in ref.get("plate", []):
        grade = r.get("material_grade", "")
        t = _f(r.get("thickness_mm"))
        rec, con = _f(r.get(_REC_KG)), _f(r.get(_CON_KG))
        key = "PL_%s_t%s" % (grade, _g(t))
        rq, cq = apply_quote_factor(rec), apply_quote_factor(con)
        label = "板 %s t%s｜通常 %s円/kg（元%s）｜安全側 %s円/kg（元%s）｜安全係数%s" % (
            grade, _g(t), _g(rq) or "—", _g(rec) or "—", _g(cq) or "—", _g(con) or "—",
            _g(QUOTE_PRICE_FACTOR))
        out.append({"key": key, "label": label, "category": "plate",
                    "material_grade": grade, "recommended_per_kg": rec,
                    "conservative_per_kg": con,
                    "recommended_per_kg_quoted": rq, "conservative_per_kg_quoted": cq})
    for r in ref.get("shape", []):
        cat = r.get("material_category", "")
        grade = r.get("material_grade", "")
        d, w, h, t = (_f(r.get("diameter_mm")), _f(r.get("width_mm")),
                      _f(r.get("height_mm")), _f(r.get("thickness_mm")))
        rec, con = _f(r.get(_REC_KG)), _f(r.get(_CON_KG))
        if cat == "square_pipe":
            key = "SQPIPE_%s_%sx%s_t%s" % (grade, _g(w), _g(h), _g(t))
        elif cat == "round_pipe":
            key = "PIPE_%s_D%s_t%s" % (grade, _g(d), _g(t))
        elif cat == "flat_bar":
            key = "FB_%s_%sx%s" % (grade, _g(w), _g(t))
        elif cat == "round_bar":
            key = "RBAR_%s_D%s" % (grade, _g(d))
        elif cat == "angle":
            key = "ANGLE_%s_%sx%s_t%s" % (grade, _g(w), _g(h), _g(t))
        else:
            key = "%s_%s" % (cat, grade)
        # display_spec には既に種別名が含まれるため、無い時だけ _JP_CAT を前置
        disp = r.get("display_spec", "") or ("%s %s" % (_JP_CAT.get(cat, cat), key))
        rq, cq = apply_quote_factor(rec), apply_quote_factor(con)
        if rec is not None:
            label = "%s｜通常 %s円/kg（元%s）｜安全係数%s" % (
                disp, _g(rq), _g(rec), _g(QUOTE_PRICE_FACTOR))
        else:
            label = "%s｜通常 —（kg単価なし→手入力）" % disp
        out.append({"key": key, "label": label, "category": cat,
                    "material_grade": grade, "recommended_per_kg": rec,
                    "conservative_per_kg": con,
                    "recommended_per_kg_quoted": rq, "conservative_per_kg_quoted": cq})
    return out


def find_price_entry(catalog, key):
    for e in catalog:
        if e["key"] == key:
            return e
    return None


def resolve_unit_price(entry, pricing_mode, manual_value=None, factor=None):
    """pricing_mode に応じた円/kg(税抜)を返す。(unit_price, warning)。

    recommended/median → recommended_per_kg × 安全係数(10円切上)、
    conservative/max → conservative_per_kg × 安全係数(10円切上)、
    manual → manual_value（**安全係数を掛けない**＝ユーザー入力値そのまま）。
    kg単価が無いカテゴリ(angle等)は manual を促す。
    """
    mode = (pricing_mode or "recommended").lower()
    if mode == "manual":
        v = _f(manual_value)
        return (v, "" if v is not None else "manual単価が未入力")
    if mode in ("conservative", "max"):
        raw = entry.get("conservative_per_kg") if entry else None
        raw = raw if raw is not None else (entry.get("recommended_per_kg") if entry else None)
    else:  # recommended / median
        raw = entry.get("recommended_per_kg") if entry else None
    if raw is None:
        return (None, "この単価カテゴリにkg単価がありません（manualで入力してください）")
    return (apply_quote_factor(raw, factor), "")


def compute_cost(raw_volume_mm3, density_g_cm3, unit_price_per_kg):
    """(weight_kg, cost_jpy, volume_m3)。

    volume_m3 = raw_volume_mm3 / 1e9、weight_kg = volume_m3 × (density×1000)。
    """
    vol = _f(raw_volume_mm3) or 0.0
    dens = _f(density_g_cm3)
    volume_m3 = vol / 1000000000.0
    weight_kg = volume_m3 * (dens * 1000.0) if dens is not None else None
    up = _f(unit_price_per_kg)
    cost = weight_kg * up if (weight_kg is not None and up is not None) else None
    return weight_kg, cost, volume_m3


# ---- 設定の保存/読込（前回値を初期表示するため） ----

def _rhino_scripts_dir():
    return os.path.join(os.path.expanduser("~"), "Documents", "RhinoScripts")


def default_settings_path():
    return os.path.join(_rhino_scripts_dir(), "weight_calc_settings.json")


def quote_settings_path():
    return os.path.join(_rhino_scripts_dir(), "quote_settings.json")


def mass_settings_path():
    return os.path.join(_rhino_scripts_dir(), "mass_settings.json")


def load_settings(path=None):
    path = path or default_settings_path()
    if not os.path.exists(path):
        return {}
    try:
        with io.open(path, encoding="utf-8") as f:
            return _json.load(f)
    except Exception:
        return {}


def save_settings(data, path=None, now_str=None):
    path = path or default_settings_path()
    folder = os.path.dirname(os.path.abspath(path))
    if folder and not os.path.isdir(folder):
        os.makedirs(folder, exist_ok=True)
    out = dict(data)
    if now_str is not None:
        out["last_updated"] = now_str
    with io.open(path, "w", encoding="utf-8") as f:
        _json.dump(out, f, ensure_ascii=False, indent=2)
    return path
