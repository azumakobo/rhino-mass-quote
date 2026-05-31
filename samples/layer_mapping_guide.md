# layer_mapping.csv 記入ガイド

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
