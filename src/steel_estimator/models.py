"""データモデル定義。

抽出1行 = 1 MaterialRecord。概算見積の入力は MaterialRequest。
すべての寸法は mm、金額は通貨単位（既定 JPY）。
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict, fields
from typing import Optional


class MaterialCategory:
    """材料カテゴリ定数。"""

    ROUND_PIPE = "round_pipe"
    SQUARE_PIPE = "square_pipe"
    ANGLE = "angle"
    CHANNEL = "channel"
    FLAT_BAR = "flat_bar"
    PLATE = "plate"
    ROUND_BAR = "round_bar"
    SQUARE_BAR = "square_bar"
    H_BEAM = "h_beam"
    ROLLED = "rolled"
    UNKNOWN = "unknown"

    ALL = (
        ROUND_PIPE, SQUARE_PIPE, ANGLE, CHANNEL, FLAT_BAR,
        PLATE, ROUND_BAR, SQUARE_BAR, H_BEAM, ROLLED, UNKNOWN,
    )


# 抽出レコードの正準フィールド順（CSVヘッダー・DB列に共通利用）
MATERIAL_FIELDS = (
    "source_pdf_path",
    "source_pdf_filename",
    "page_number",
    "raw_text_line",
    "vendor_name",
    "quote_date",
    "item_name_original",
    "material_category",
    "material_grade",
    "shape_token",
    "dimension_text_original",
    "diameter_mm",
    "width_mm",
    "height_mm",
    "thickness_mm",
    "length_mm",
    "plate_width_mm",
    "plate_height_mm",
    "quantity",
    "unit",
    "unit_price",
    "amount",
    "currency",
    "confidence",
    "needs_review",
    "notes",
)


@dataclass
class MaterialRecord:
    """見積PDFから抽出した1材料行。"""

    source_pdf_path: str = ""
    source_pdf_filename: str = ""
    page_number: int = 0
    raw_text_line: str = ""
    vendor_name: str = ""
    quote_date: str = ""  # ISO形式 YYYY-MM-DD（不明は空）
    item_name_original: str = ""
    material_category: str = MaterialCategory.UNKNOWN
    material_grade: str = ""
    shape_token: str = ""
    dimension_text_original: str = ""
    diameter_mm: Optional[float] = None
    width_mm: Optional[float] = None
    height_mm: Optional[float] = None
    thickness_mm: Optional[float] = None
    length_mm: Optional[float] = None
    plate_width_mm: Optional[float] = None
    plate_height_mm: Optional[float] = None
    quantity: Optional[float] = None
    unit: str = ""
    unit_price: Optional[float] = None
    amount: Optional[float] = None
    currency: str = "JPY"
    confidence: float = 0.0
    needs_review: bool = True
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    def add_note(self, note: str) -> None:
        if not note:
            return
        self.notes = f"{self.notes}; {note}".strip("; ") if self.notes else note


@dataclass
class MaterialRequest:
    """概算見積の入力1行（material_request.csv）。"""

    item_name: str = ""
    material_category: str = ""
    material_grade: str = ""
    width_mm: Optional[float] = None
    height_mm: Optional[float] = None
    diameter_mm: Optional[float] = None
    thickness_mm: Optional[float] = None
    length_mm: Optional[float] = None
    plate_width_mm: Optional[float] = None
    plate_height_mm: Optional[float] = None
    quantity: Optional[float] = None
    unit: str = ""
    notes: str = ""

    @classmethod
    def from_row(cls, row: dict) -> "MaterialRequest":
        kwargs = {}
        for f in fields(cls):
            raw = row.get(f.name, "")
            if raw is None:
                raw = ""
            raw = str(raw).strip()
            if f.type == "Optional[float]" or "float" in str(f.type):
                kwargs[f.name] = _to_float(raw)
            else:
                kwargs[f.name] = raw
        return cls(**kwargs)


REQUEST_FIELDS = tuple(f.name for f in fields(MaterialRequest))

# 概算見積結果のCSVヘッダー（estimated_amount は税抜）
ESTIMATE_RESULT_FIELDS = (
    "item_name",
    "requested_spec",
    "quantity",
    "estimated_unit_price",
    "estimated_amount",
    "estimated_amount_ex_tax",
    "tax_rate",
    "estimated_tax_amount",
    "estimated_amount_inc_tax",
    "estimate_basis",
    "accuracy_level",
    "matched_source_pdf",
    "matched_vendor",
    "matched_quote_date",
    "warning",
)


def _to_float(s: str) -> Optional[float]:
    s = (s or "").replace(",", "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None
