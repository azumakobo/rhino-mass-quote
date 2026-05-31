"""PDFテキスト/表抽出と MaterialRecord 化。

主経路: 東鋼材フォーマットのテーブルを列マッピングで解釈（高信頼）。
従経路: 表が取れない場合、本文行をフリーテキストパースにかける。
"""

from __future__ import annotations

import os
import re
from typing import Iterator, Optional

import pdfplumber

from .models import MaterialRecord, MaterialCategory as C
from . import material_parser as mp


# 東鋼材フォーマットのヘッダー（正規化後に照合）
TOKO_HEADER_KEYS = ("品番", "材質", "形状", "板厚", "寸1", "寸2")

# 形状名 → カテゴリ
SHAPE_TO_CATEGORY = {
    "アングル": C.ANGLE,
    "角パイプ": C.SQUARE_PIPE,
    "丸パイプ": C.ROUND_PIPE,
    "丸棒": C.ROUND_BAR,
    "FB": C.FLAT_BAR,
    "切板": C.PLATE,
    "型切": C.PLATE,
    "H形鋼": C.H_BEAM,
    "ロール巻き": C.ROLLED,
    "チャンネル": C.CHANNEL,
    "角棒": C.SQUARE_BAR,
    "鉄板": C.PLATE,
    "鋼板": C.PLATE,
}

# 曲げ・巻き等の「加工品」トークン。単価に加工費が含まれ寸法も変形するため、
# 生材（raw material）の単価マスターからは除外し unknown へ退避する。
FABRICATION_TOKENS = ("曲げ", "巻き", "ロール")

DATE_RE = re.compile(r"(20\d{2})\s*[/年.]\s*(\d{1,2})\s*[/月.]\s*(\d{1,2})")
VENDOR_HINTS = ("鋼材", "鋼業", "製作所", "工業", "商店", "株式会社", "（株）", "(株)")


def _norm(s: Optional[str]) -> str:
    return (s or "").replace("\n", " ").strip()


def extract_quote_date(text: str) -> str:
    """本文から見積日を ISO(YYYY-MM-DD)で抽出。見つからなければ空。"""
    m = DATE_RE.search(text or "")
    if not m:
        return ""
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return f"{y:04d}-{mo:02d}-{d:02d}"
    except ValueError:
        return ""


def extract_vendor(text: str) -> str:
    """発行業者名を推定。'鋼材' 等のヒントを含む行を優先。"""
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or "様" in line:  # '様' は宛先行なので除外
            continue
        for hint in VENDOR_HINTS:
            if hint in line:
                # 末尾の担当者名（空白以降）を落として業者名のみ返す
                return line.split()[0] if " " in line else line
    return ""


def _looks_like_toko_header(row: list) -> bool:
    joined = " ".join(_norm(c) for c in row if c)
    return sum(1 for k in TOKO_HEADER_KEYS if k in joined) >= 4


def interpret_toko_row(header: list, row: list, ctx: dict) -> Optional[MaterialRecord]:
    """東鋼材テーブルの1行を MaterialRecord に変換。

    列の意味は「形状」依存（design.md §2 参照）。
    """
    cells = {}
    for h, v in zip(header, row):
        cells[_norm(h)] = _norm(v)

    shape = cells.get("形状", "")
    item = cells.get("品番", "")
    if not shape and not item:
        return None
    # 合計行など（No.が空で品番も空）はスキップ
    no = cells.get("No.", "") or cells.get("No．", "")
    grade = cells.get("材質", "")
    itanmae = cells.get("板厚", "")   # 形状により径/H寸法のことも
    dim1 = cells.get("寸1", "")
    dim2 = cells.get("寸2", "")
    qty = mp.normalize_number(cells.get("ＱＴＹ", "") or cells.get("QTY", ""))
    unit_price = mp.normalize_number(cells.get("金額/個", ""))
    amount = mp.normalize_number(cells.get("金額/台", ""))
    notes_remark = cells.get("備考", "")

    # 「品番」が空＝直前行の連続単価（"4 -> "4 のような派生行）。スキップせず取り込む。
    category = SHAPE_TO_CATEGORY.get(shape) or mp.classify_category(f"{item} {shape}")

    # 加工品（曲げ・巻き）は単価に加工費を含み寸法も変形するため、
    # ロール巻きを除き生材カテゴリから unknown へ退避（材料費マスターを汚さない）。
    # 長さ列(寸2)が複数寸法を含む（例 "313.6x574.4x627.2 x..."）＝曲げフレーム等の
    # 多分割加工品で、直線長さではない。生材以外として扱う。
    dim2_is_multiseg = category in (
        C.ROUND_PIPE, C.ROUND_BAR, C.SQUARE_PIPE, C.ANGLE,
        C.FLAT_BAR, C.CHANNEL, C.H_BEAM,
    ) and len(re.findall(r"[x×X]", dim2)) >= 1

    is_fabricated = (
        any(tok in f"{shape} {item}" for tok in FABRICATION_TOKENS)
        or dim2_is_multiseg
    ) and category != C.ROLLED
    if is_fabricated:
        category = C.UNKNOWN

    rec = MaterialRecord(
        source_pdf_path=ctx["path"],
        source_pdf_filename=ctx["filename"],
        page_number=ctx["page_number"],
        raw_text_line=" | ".join(_norm(c) for c in row),
        vendor_name=ctx.get("vendor", ""),
        quote_date=ctx.get("quote_date", ""),
        item_name_original=item,
        material_category=category,
        material_grade=grade or mp.extract_grade(item),
        dimension_text_original=f"板厚={itanmae} 寸1={dim1} 寸2={dim2}",
        quantity=qty,
        unit="個",
        unit_price=unit_price,
        amount=amount,
        currency="JPY",
        confidence=0.9,
        needs_review=False,
        notes=notes_remark,
    )
    rec.shape_token = mp.detect_shape_token(f"{itanmae} {item}", category)

    _map_dimensions_by_shape(rec, category, itanmae, dim1, dim2)

    if is_fabricated:
        rec.add_note(f"加工品({shape}): 単価に加工費含む・生材マスター対象外")
        rec.needs_review = True

    # アルミ等、鉄密度計算が不適な材質は警告
    if rec.material_grade.startswith("A") and rec.material_grade[1:].isdigit() or rec.material_grade == "AL":
        rec.add_note("アルミ材: 鉄密度での重量計算は不可")
    if not rec.material_grade:
        rec.add_note("材質不明")
        rec.needs_review = True
    return rec


def _map_dimensions_by_shape(rec, category, itanmae, dim1, dim2):
    """形状ごとの列意味マッピング。"""
    phi_in_itanmae = "φ" in itanmae or "Φ" in itanmae

    if category in (C.ROUND_PIPE, C.ROLLED):
        rec.diameter_mm = mp.normalize_number(itanmae)
        rec.thickness_mm = mp.normalize_number(dim1)
        rec.length_mm = mp.parse_length_token(dim2)

    elif category == C.ROUND_BAR:
        rec.diameter_mm = mp.normalize_number(itanmae)
        rec.length_mm = mp.parse_length_token(dim2)

    elif category in (C.ANGLE, C.SQUARE_PIPE, C.CHANNEL):
        rec.thickness_mm = mp.normalize_number(itanmae)
        w, h = mp.parse_pair(dim1)
        rec.width_mm, rec.height_mm = w, h
        rec.length_mm = mp.parse_length_token(dim2)

    elif category == C.FLAT_BAR:
        rec.thickness_mm = mp.normalize_number(itanmae)
        rec.width_mm = mp.normalize_number(dim1)
        rec.length_mm = mp.parse_length_token(dim2)

    elif category == C.PLATE:
        rec.thickness_mm = mp.normalize_number(itanmae)
        rec.plate_width_mm = mp.normalize_number(dim1)
        rec.plate_height_mm = mp.normalize_number(dim2)
        if rec.notes and "型切" not in rec.notes and itanmae:
            pass
        # 型切（異形）は外接矩形のため面積過大の可能性を明記
        if rec.item_name_original and "型切" in rec.item_name_original:
            rec.add_note("型切(異形): 寸法は外接矩形")
            rec.needs_review = True

    elif category == C.H_BEAM:
        h, b = mp.parse_pair(itanmae)
        rec.height_mm, rec.width_mm = h, b
        t1, t2 = mp.parse_pair(dim1)  # web/flange 厚
        rec.thickness_mm = t1
        rec.length_mm = mp.parse_length_token(dim2)
        rec.add_note("H形鋼: 重量はJIS表参照が必要（v1未対応）")
        rec.needs_review = True

    else:  # UNKNOWN / SQUARE_BAR
        if phi_in_itanmae:
            rec.diameter_mm = mp.normalize_number(itanmae)
        else:
            rec.thickness_mm = mp.normalize_number(itanmae)
        w, h = mp.parse_pair(dim1)
        rec.width_mm, rec.height_mm = w, h
        rec.length_mm = mp.parse_length_token(dim2)
        rec.confidence = 0.4
        rec.needs_review = True


def interpret_text_line(line: str, ctx: dict) -> Optional[MaterialRecord]:
    """フリーテキスト経路: 1行から材料候補を抽出（フォールバック）。"""
    line = line.strip()
    if len(line) < 4:
        return None
    category = mp.classify_category(line)
    if category == C.UNKNOWN and not (mp.PHI_RE.search(line) or "×" in line or "x" in line):
        return None

    dims = mp.parse_dimension_text(line, category)
    rec = MaterialRecord(
        source_pdf_path=ctx["path"],
        source_pdf_filename=ctx["filename"],
        page_number=ctx["page_number"],
        raw_text_line=line,
        vendor_name=ctx.get("vendor", ""),
        quote_date=ctx.get("quote_date", ""),
        item_name_original=line,
        material_category=category,
        material_grade=mp.extract_grade(line),
        shape_token=mp.detect_shape_token(line, category),
        dimension_text_original=line,
        diameter_mm=dims["diameter_mm"],
        width_mm=dims["width_mm"],
        height_mm=dims["height_mm"],
        thickness_mm=dims["thickness_mm"],
        length_mm=dims["length_mm"],
        plate_width_mm=dims["plate_width_mm"],
        plate_height_mm=dims["plate_height_mm"],
        confidence=0.5,
        needs_review=dims["needs_review"] or category == C.UNKNOWN,
        notes=dims["notes"],
    )
    return rec


def extract_records_from_pdf(path: str) -> list[MaterialRecord]:
    """1 PDF から MaterialRecord のリストを抽出。"""
    filename = os.path.basename(path)
    records: list[MaterialRecord] = []

    with pdfplumber.open(path) as pdf:
        # 先頭ページ本文から業者・日付を推定（全ページ共通とみなす）
        first_text = pdf.pages[0].extract_text() or "" if pdf.pages else ""
        vendor = extract_vendor(first_text)
        quote_date = extract_quote_date(first_text)

        for pno, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            ctx = {
                "path": path, "filename": filename, "page_number": pno,
                "vendor": vendor, "quote_date": quote_date or extract_quote_date(text),
            }
            tables = page.extract_tables() or []
            handled = False
            for table in tables:
                if not table or len(table) < 2:
                    continue
                header = table[0]
                if not _looks_like_toko_header(header):
                    continue
                handled = True
                for row in table[1:]:
                    if not any(_norm(c) for c in row):
                        continue
                    rec = interpret_toko_row(header, row, ctx)
                    if rec and (rec.unit_price is not None or rec.diameter_mm is not None
                                or rec.thickness_mm is not None or rec.width_mm is not None):
                        records.append(rec)
            if not handled:
                # フォールバック: 本文行をフリーテキストパース
                for line in text.splitlines():
                    rec = interpret_text_line(line, ctx)
                    if rec:
                        records.append(rec)
    return records
