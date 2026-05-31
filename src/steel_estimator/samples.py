"""サンプル一式（init-samples）の生成。

日本語レイヤー名を含む rhino_objects / 確定済み layer_mapping / cost_items を用意し、
そこから layer_summary / estimate_result / estimate_summary を実際に計算して書き出す。
"""

from __future__ import annotations

import os

from . import csv_utils as cu
from . import rhino_csv
from . import layer_summary as lsum
from . import layer_mapping as lmap
from . import cost_items as citems
from . import layer_estimate as lest


# --- サンプル rhino_objects（mmはRhino既定単位想定） ---
RHINO_SAMPLE = [
    {"file_name": "sample.3dm", "layer_name": "鉄板6mm", "object_id": "A1",
     "object_name": "天板", "object_type": "Surface", "object_count": 1,
     "object_area_mm2": 1000000, "object_volume_mm3": "", "object_curve_length_mm": "",
     "bounding_box_width_mm": 1000, "bounding_box_height_mm": 1000, "bounding_box_depth_mm": 6,
     "is_closed_curve": "false", "is_closed_brep": "false", "is_surface": "true",
     "is_mesh": "false", "is_curve": "false", "notes": ""},
    {"file_name": "sample.3dm", "layer_name": "鉄板6mm", "object_id": "A2",
     "object_name": "側板", "object_type": "Surface", "object_count": 1,
     "object_area_mm2": 1000000, "object_volume_mm3": "", "object_curve_length_mm": "",
     "bounding_box_width_mm": 1000, "bounding_box_height_mm": 1000, "bounding_box_depth_mm": 6,
     "is_closed_curve": "false", "is_closed_brep": "false", "is_surface": "true",
     "is_mesh": "false", "is_curve": "false", "notes": ""},
    {"file_name": "sample.3dm", "layer_name": "角パイプ_50", "object_id": "B1",
     "object_name": "脚1", "object_type": "Curve", "object_count": 1,
     "object_area_mm2": "", "object_volume_mm3": "", "object_curve_length_mm": 6000,
     "bounding_box_width_mm": 50, "bounding_box_height_mm": 50, "bounding_box_depth_mm": 6000,
     "is_closed_curve": "false", "is_closed_brep": "false", "is_surface": "false",
     "is_mesh": "false", "is_curve": "true", "notes": ""},
    {"file_name": "sample.3dm", "layer_name": "角パイプ_50", "object_id": "B2",
     "object_name": "脚2", "object_type": "Curve", "object_count": 1,
     "object_area_mm2": "", "object_volume_mm3": "", "object_curve_length_mm": 6000,
     "bounding_box_width_mm": 50, "bounding_box_height_mm": 50, "bounding_box_depth_mm": 6000,
     "is_closed_curve": "false", "is_closed_brep": "false", "is_surface": "false",
     "is_mesh": "false", "is_curve": "true", "notes": ""},
    {"file_name": "sample.3dm", "layer_name": "角パイプ_50", "object_id": "B3",
     "object_name": "梁", "object_type": "Curve", "object_count": 1,
     "object_area_mm2": "", "object_volume_mm3": "", "object_curve_length_mm": 6000,
     "bounding_box_width_mm": 50, "bounding_box_height_mm": 50, "bounding_box_depth_mm": 6000,
     "is_closed_curve": "false", "is_closed_brep": "false", "is_surface": "false",
     "is_mesh": "false", "is_curve": "true", "notes": ""},
    {"file_name": "sample.3dm", "layer_name": "丸パイプ手すり", "object_id": "C1",
     "object_name": "手すり", "object_type": "Curve", "object_count": 1,
     "object_area_mm2": "", "object_volume_mm3": "", "object_curve_length_mm": 12000,
     "bounding_box_width_mm": 42.7, "bounding_box_height_mm": 900, "bounding_box_depth_mm": 12000,
     "is_closed_curve": "false", "is_closed_brep": "false", "is_surface": "false",
     "is_mesh": "false", "is_curve": "true", "notes": "SUS304 φ42.7"},
    {"file_name": "sample.3dm", "layer_name": "ソリッド部品", "object_id": "D1",
     "object_name": "ブラケット", "object_type": "Brep", "object_count": 1,
     "object_area_mm2": "", "object_volume_mm3": 2000000, "object_curve_length_mm": "",
     "bounding_box_width_mm": 200, "bounding_box_height_mm": 100, "bounding_box_depth_mm": 100,
     "is_closed_curve": "false", "is_closed_brep": "true", "is_surface": "false",
     "is_mesh": "false", "is_curve": "false", "notes": "鋳物的形状"},
    {"file_name": "sample.3dm", "layer_name": "ボルト類", "object_id": "E1",
     "object_name": "M12ボルト", "object_type": "Point", "object_count": 24,
     "object_area_mm2": "", "object_volume_mm3": "", "object_curve_length_mm": "",
     "bounding_box_width_mm": "", "bounding_box_height_mm": "", "bounding_box_depth_mm": "",
     "is_closed_curve": "false", "is_closed_brep": "false", "is_surface": "false",
     "is_mesh": "false", "is_curve": "false", "notes": "購入部品"},
    {"file_name": "sample.3dm", "layer_name": "補助線", "object_id": "F1",
     "object_name": "通り芯", "object_type": "Curve", "object_count": 1,
     "object_area_mm2": "", "object_volume_mm3": "", "object_curve_length_mm": 5000,
     "bounding_box_width_mm": 5000, "bounding_box_height_mm": 0, "bounding_box_depth_mm": 0,
     "is_closed_curve": "false", "is_closed_brep": "false", "is_surface": "false",
     "is_mesh": "false", "is_curve": "true", "notes": "検討用"},
    {"file_name": "sample.3dm", "layer_name": "曲げ加工", "object_id": "G1",
     "object_name": "曲げ指示", "object_type": "Curve", "object_count": 1,
     "object_area_mm2": "", "object_volume_mm3": "", "object_curve_length_mm": 1000,
     "bounding_box_width_mm": "", "bounding_box_height_mm": "", "bounding_box_depth_mm": "",
     "is_closed_curve": "false", "is_closed_brep": "false", "is_surface": "false",
     "is_mesh": "false", "is_curve": "true", "notes": "加工費(材料費と分離)"},
    {"file_name": "sample.3dm", "layer_name": "塗装費", "object_id": "H1",
     "object_name": "塗装範囲", "object_type": "Annotation", "object_count": 1,
     "object_area_mm2": "", "object_volume_mm3": "", "object_curve_length_mm": "",
     "bounding_box_width_mm": "", "bounding_box_height_mm": "", "bounding_box_depth_mm": "",
     "is_closed_curve": "false", "is_closed_brep": "false", "is_surface": "false",
     "is_mesh": "false", "is_curve": "false", "notes": ""},
    {"file_name": "sample.3dm", "layer_name": "運搬費", "object_id": "I1",
     "object_name": "運搬", "object_type": "Annotation", "object_count": 1,
     "object_area_mm2": "", "object_volume_mm3": "", "object_curve_length_mm": "",
     "bounding_box_width_mm": "", "bounding_box_height_mm": "", "bounding_box_depth_mm": "",
     "is_closed_curve": "false", "is_closed_brep": "false", "is_surface": "false",
     "is_mesh": "false", "is_curve": "false", "notes": ""},
]


def _mrow(**kw) -> dict:
    """mapping行を MAPPING_FIELDS で初期化して上書き。"""
    base = {f: "" for f in lmap.MAPPING_FIELDS}
    base["enabled"] = "true"
    base["waste_rate"] = "1.0"
    base.update(kw)
    return base


# --- 確定済み layer_mapping（単価入りの実用例） ---
MAPPING_SAMPLE = [
    _mrow(layer_name="鉄板6mm", calc_type="area_to_weight", material_category="plate",
          material_grade="SS400", spec_text="SS400 t6", thickness_mm="6",
          density_g_cm3="7.85", unit_price="150", price_unit="kg", waste_rate="1.1",
          price_source="社内基準", notes="鉄板。面積×板厚×密度×歩留でkg、kg単価150円"),
    _mrow(layer_name="角パイプ_50", calc_type="curve_length_to_stock",
          material_category="square_pipe", material_grade="STKR", spec_text="□50x50x2.3",
          width_mm="50", height_mm="50", thickness_mm="2.3", stock_length_mm="6000",
          unit_price="3880", price_unit="stock", waste_rate="1.1",
          price_source="過去見積", notes="定尺6mで本数算出"),
    _mrow(layer_name="丸パイプ手すり", calc_type="curve_length_to_meter",
          material_category="round_pipe", material_grade="SUS304", spec_text="SUS304 φ42.7",
          diameter_mm="42.7", unit_price="1200", price_unit="m", waste_rate="1.05",
          price_source="社内基準", notes="m単価で計算"),
    _mrow(layer_name="ソリッド部品", calc_type="volume_to_weight",
          material_category="unknown", material_grade="SS400", spec_text="鋳物的ブラケット",
          density_g_cm3="7.85", unit_price="300", price_unit="kg", waste_rate="1.0",
          notes="Rhinoソリッド体積から重量"),
    _mrow(layer_name="ボルト類", calc_type="object_count", spec_text="M12ボルト",
          unit_price="80", price_unit="個", notes="個数×単価"),
    _mrow(layer_name="補助線", calc_type="ignore", notes="検討用・見積対象外"),
    _mrow(layer_name="曲げ加工", calc_type="fixed_amount", fixed_amount="15000",
          price_source="加工見積", notes="加工費(生材単価と分離)"),
    _mrow(layer_name="塗装費", calc_type="fixed_amount", fixed_amount="20000",
          notes="塗装一式"),
    _mrow(layer_name="運搬費", calc_type="fixed_amount", fixed_amount="18000",
          notes="運搬一式"),
]


COST_SAMPLE = [
    {"item_name": "レーザー切断", "cost_category": "cutting", "calc_type": "fixed_amount",
     "quantity": "", "unit": "", "unit_price": "", "fixed_amount": "12000", "notes": "切断一式"},
    {"item_name": "溶接組立", "cost_category": "welding", "calc_type": "quantity",
     "quantity": "8", "unit": "箇所", "unit_price": "2500", "fixed_amount": "", "notes": "8箇所"},
    {"item_name": "現場取付", "cost_category": "installation", "calc_type": "fixed_amount",
     "quantity": "", "unit": "", "unit_price": "", "fixed_amount": "30000", "notes": "据付一式"},
]


GUIDE = """# layer_mapping.csv 記入ガイド

## 基本思想
- **計算の正は `layer_mapping.csv`**。Rhinoレイヤー名の自動推定は初期値の候補にすぎません。
- PDF解析DB（過去見積）は「単価候補・根拠表示・単価未入力時の補助」に使います。確定はしません。
- 生材単価と加工費（曲げ・切断・溶接・塗装・運搬）は**混ぜない**。加工費は `cost_items.csv` か
  `calc_type=fixed_amount` のレイヤーで分離します。
- mapping 未設定・単価未入力・根拠が弱い項目は、止めずに `needs_review=true` / `warning` で出力します。

## 列の意味（抜粋）
- `enabled`: false で計算対象外（結果には ignored として残る）。
- `calc_type`: 計算方式（下表）。`ignore` も対象外（ignoredとして残る）。
- `unit_price`: ここに入れた単価が最優先。空なら manual_prices → PDF DB の順で候補を探します。
- `price_unit`: calc_type と整合させる（不整合は warning）。
- `waste_rate`: 歩留・端材率（例 1.1 = +10%）。空欄は 1.0。
- `density_g_cm3`: 空欄時は 7.85（鉄）を仮定。SUS304≈7.93、アルミ≈2.70 は手入力で上書き。

## calc_type 一覧と計算式
| calc_type | 用途 | 計算式 | price_unit |
|---|---|---|---|
| area_to_weight | 鉄板・板材 | weight_kg = area_m2 × thickness_mm × density × waste / 金額 = weight×kg単価 | kg |
| volume_to_weight | ソリッド・異形 | weight_kg = volume_mm3 × density × 1e-6 × waste | kg |
| curve_length_to_stock | パイプ・アングル等(定尺) | 本数 = ceil(length_m×1000 / stock_length × waste) / 金額 = 本数×単価 | stock / 6m |
| curve_length_to_meter | m単価材 | 金額 = length_m × waste × m単価 | m |
| object_count | ボルト・金物・購入品 | 金額 = object_count × 単価 | 個 |
| manual_quantity | 人間が数量指定 | 金額 = quantity_override × 単価 | 任意 |
| fixed_amount | 加工費・運搬費・設計費等 | 金額 = fixed_amount | - |
| ignore | 補助線・注釈・検討 | 計算しない（ignoredとして残す） | - |

## needs_review / warning になる条件
- mappingに無いレイヤー → needs_review。
- calc_typeが単価を要するのに `unit_price` が空 → needs_review。
- area_to_weight で `thickness_mm` が空 → warning + needs_review。
- 数量根拠（面積/長さ/体積/個数）が 0 または欠落 → warning。
- `stock_length_mm` 未指定 → 6000mm を仮定し warning。
- `price_unit` と `calc_type` が不整合 → warning。

## 加工費・運搬費・塗装費の追加方法
1. `cost_items.csv` に費目を書き、`estimate-by-layer --cost-items` で合算（推奨）。
2. または Rhinoレイヤーとして `calc_type=fixed_amount` を割り当てる。
いずれも材料費（material）とは別カテゴリ（processing/transport/installation/design）で集計されます。

## calc_type の使い分け早見表
| こういうレイヤー | calc_type |
|---|---|
| 鉄板・板材（面積で重量） | area_to_weight |
| ソリッド部品・異形・鋳物的形状（体積で重量） | volume_to_weight |
| パイプ・角パイプ・アングルの中心線（定尺本数） | curve_length_to_stock |
| パイプ等を m 単価で買う場合 | curve_length_to_meter |
| ボルト・金物・購入部品（個数） | object_count |
| 人間が数量を直接指定 | manual_quantity |
| 曲げ加工・塗装費・運搬費・設計費（固定額） | fixed_amount（または cost_items.csv） |
| 補助線・通り芯・注釈・検討用 | ignore |

## price_unit の例
- `kg` … area_to_weight / volume_to_weight（kg単価）
- `m`  … curve_length_to_meter（メートル単価）
- `stock` または `6m` … curve_length_to_stock（定尺1本あたり単価）
- `piece` / `個` … object_count
- `lot` … 一式（manual_quantity 等で使用）
- `fixed` … fixed_amount（金額そのもの）

## density_g_cm3 の例（材料名から自動確定せず手入力する）
- SS400（鉄鋼）: 7.85
- SUS304（ステンレス）: 7.93
- aluminum（アルミ A5052 等）: 2.70
未指定時は 7.85（鉄）を仮定し warning を出します。

## mapping未設定の行の扱い
- `init/update-layer-mapping` で全レイヤーの雛形が作られますが、`unit_price` 等が空のままだと
  見積では `needs_review=true` / `accuracy_level=unknown` として出力されます（止まりません）。
- `run-rhino-estimate` の `rhino_estimate_report.md` に「未設定レイヤー一覧」が出るので、そこを優先的に埋めます。

## 注意（必ず守ること）
- **材料費と加工費を混ぜない**（加工費は cost_items.csv か fixed_amount に分離）。
- **PDF由来の加工品単価を生材単価として使わない**（曲げ・型切等は加工費込み）。
- 本見積は**概算**であり、最終発注前に必ず人間が確認する。
"""


def write_samples(out_dir: str) -> list[str]:
    os.makedirs(out_dir, exist_ok=True)
    written = []

    p = os.path.join(out_dir, "rhino_objects.csv")
    cu.write_dicts(p, rhino_csv.RHINO_OBJECT_FIELDS, RHINO_SAMPLE)
    written.append(p)

    objs = [rhino_csv.RhinoObject.from_row(r) for r in RHINO_SAMPLE]
    summary_rows = lsum.build_summary(objs)
    p = os.path.join(out_dir, "layer_summary.csv")
    lsum.write_summary(p, summary_rows)
    written.append(p)

    p = os.path.join(out_dir, "layer_mapping.csv")
    lmap.write_mapping(p, MAPPING_SAMPLE)
    written.append(p)

    p = os.path.join(out_dir, "cost_items.csv")
    cu.write_dicts(p, citems.COST_ITEM_FIELDS, COST_SAMPLE)
    written.append(p)

    results, summ = lest.estimate_layers(summary_rows, MAPPING_SAMPLE, cost_rows=COST_SAMPLE)
    p = os.path.join(out_dir, "estimate_result.csv")
    lest.write_results(p, results)
    written.append(p)
    p = os.path.join(out_dir, "estimate_summary.csv")
    lest.write_summary(p, summ)
    written.append(p)

    p = os.path.join(out_dir, "layer_mapping_guide.md")
    with open(p, "w", encoding="utf-8") as f:
        f.write(GUIDE)
    written.append(p)

    return written
