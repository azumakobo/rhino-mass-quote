# Rhinoレイヤー概算見積 設計方針（Phase R1）

最終更新: 2026-05-31

## 0. 位置づけ

既存の「過去見積PDF解析機能」（`docs/steel-estimator-design.md`）は**変更せず**、
その上に「Rhinoレイヤー別の概算見積機能」を追加する。本書はその追加分の設計。

目的は**完全自動見積ではなく**、「Rhinoレイヤーを数量根拠に、人間が計算ルールを
確定できる概算見積ツール」。レイヤー名の自動判定は信用しすぎない。

## 1. なぜ固定命名でなく layer_mapping 方式か

- レイヤー名は人・案件で異なる（例: `鉄板6mm` / `PL6` / `t6_SS400`）。固定命名規則を
  正解にすると、命名が違うだけで誤集計・誤見積になる。
- そこで「レイヤー名 → 計算ルール」の対応を**人間が編集する `layer_mapping.csv`** に外出しし、
  これを計算の唯一の正とする。自動推定（`suggested_*`）は初期値の候補にすぎない。
- mapping未設定・単価未入力でも**止めず**、`needs_review=true` / `warning` を付けて出力する
  （エラーで止めるより、未確定をレビュー対象として可視化する方を優先）。

## 2. PDF解析DB と Rhino見積の役割分担

| 要素 | 役割 |
|------|------|
| PDF解析DB（`steel_quotes.sqlite`） | **過去単価データベース**。単価候補・根拠・kg単価中央値の供給源 |
| Rhinoレイヤー集計（`layer_summary.csv`） | **今回案件の数量根拠**（面積/長さ/体積/個数） |
| `layer_mapping.csv` | **人間が確定する計算ルール**（calc_type・寸法・単価・歩留） |
| `cost_items.csv` | 加工費・運搬費など、材料費と分離する費目 |
| `estimate_result.csv` | 最終的な概算見積（明細） |
| `estimate_summary.csv` | カテゴリ別の総括 |

単価決定の優先順位:
1. `layer_mapping.csv` の `unit_price`（最優先）
2. `manual_prices.csv` の完全一致
3. PDF DB の完全一致
4. PDF DB の近似一致
5. 同一カテゴリ・同一素材の kg単価中央値（重量計算系のみ）
6. unknown

Rhino見積では基本的に 1 で単価を指定する。PDF DB（`--db`）は任意で、候補提示・補助に使う。

## 3. ファイル間の関係（データフロー）

```
rhino_objects.csv ──summarize-layers──▶ layer_summary.csv
                                              │ init/update-layer-mapping
                                              ▼
                                        layer_mapping.csv（人間が編集＝正）
                                              │
layer_summary.csv + layer_mapping.csv ──estimate-by-layer──▶ estimate_result.csv
                  + cost_items.csv（任意）                     + estimate_summary.csv
                  + PDF DB（任意・候補）
```

## 4. calc_type ごとの計算式

| calc_type | 計算式（mm/m/kg/円） | price_unit |
|---|---|---|
| area_to_weight | `weight_kg = area_m2 × thickness_mm × density × waste`、`amount = weight_kg × kg単価` | kg |
| volume_to_weight | `weight_kg = volume_mm3 × density × 1e-6 × waste`、`amount = weight_kg × kg単価` | kg |
| curve_length_to_stock | `本数 = ceil(length_m×1000 / stock_length_mm × waste)`、`amount = 本数 × 単価` | stock / `Nm` |
| curve_length_to_meter | `amount = length_m × waste × m単価` | m |
| object_count | `amount = object_count × 単価` | 個 |
| manual_quantity | `amount = quantity_override × 単価` | 任意 |
| fixed_amount | `amount = fixed_amount` | - |
| ignore | 計算しない（ignoredとして残す） | - |

- 密度: `density_g_cm3` 未指定時は 7.85（鉄）を仮定し warning。SUS304≈7.93、アルミ≈2.70 は
  材料名から自動確定せず、mapping で手入力する。
- `waste_rate` 空欄は 1.0。`stock_length_mm` 空欄は 6000mm を仮定し warning。
- area_to_weight の単位検算: `area_m2 ×(thickness_mm/1000)=体積m³`、`×density×1000=kg` → 係数は
  `area_m2 × thickness_mm × density` に約分される。

## 5. needs_review / warning の条件

needs_review=true:
- mappingに無いレイヤー
- 単価が必須な calc_type で `unit_price` が空
- area_to_weight で `thickness_mm` が空
- 数量根拠（面積/長さ/体積/個数）が欠落
- accuracy_level=unknown

warning（計算は続行）:
- thickness/density/stock_length の未指定（既定値を仮定した旨）
- 数量根拠が 0
- `price_unit` と `calc_type` の不整合
- 未知の calc_type

accuracy_level: `manual_mapping / manual_price / exact / close / formula / fixed / ignored / unknown`。

## 6. 加工費・外注費の分離

生材単価と加工費（曲げ・型切・溶接・塗装・運搬・施工）は混ぜない。
- `cost_items.csv`（推奨）: `--cost-items` で合算。`cost_category` で processing/transport/
  installation/design に振り分け。
- または `calc_type=fixed_amount` のレイヤー。レイヤー名から費目を推定して総括カテゴリに分類。

PDF解析側で発見された「曲げ加工品が生材単価を汚染する」問題（design.md §修正履歴）と同じ思想で、
材料費（material）と加工費を `estimate_summary.csv` 上で別カテゴリに集計する。

## 7. 実務上の限界

- レイヤー集計の精度は Rhino 側の作図品質に依存（面積=サーフェス前提、長さ=曲線前提）。
- アングル/チャンネル/H形鋼の重量はJIS表未搭載。area/volume か単価指定で代替。
- 自動推定（suggested_*）は補助。確定は人間の mapping 編集に委ねる。
- PDF DB の単価は過去時点・他寸法のものを含むため、close/formula は誤差を warning で明示。
- 異形・曲げ加工品はバウンディングボックスや外接寸法では実量を表さない。

## 7.5 layer_mapping 編集の指針（calc_type / price_unit / density）

最終的に人間が編集するのは `layer_mapping.csv`。迷ったら下表で選ぶ。

| レイヤーの性質 | calc_type | price_unit 例 |
|---|---|---|
| 鉄板・板材（面積→重量） | area_to_weight | kg |
| ソリッド部品・異形（体積→重量） | volume_to_weight | kg |
| パイプ/角パイプ/アングルの中心線（定尺本数） | curve_length_to_stock | stock / 6m |
| パイプ等を m 単価で購入 | curve_length_to_meter | m |
| ボルト・金物・購入部品 | object_count | piece / 個 |
| 人間が数量指定 | manual_quantity | lot 等 |
| 曲げ加工・塗装費・運搬費・設計費 | fixed_amount（or cost_items.csv） | fixed |
| 補助線・注釈・検討用 | ignore | - |

density_g_cm3 の代表値（**材料名から自動確定せず手入力**。未指定は 7.85 を仮定し warning）:
SS400=7.85 / SUS304=7.93 / aluminum=2.70。

mapping未設定（unit_price 空など）の行は止めずに `needs_review=true` / `accuracy_level=unknown`
で出力し、`rhino_estimate_report.md` の「未設定レイヤー一覧」に列挙する。

原則の再確認:
- 材料費と加工費を混ぜない（加工費は cost_items.csv か fixed_amount）。
- PDF由来の加工品単価を生材単価として使わない。
- 見積は概算。最終発注前に人間が確認する。

## 7.6 一括実行と監査（Phase R3）

- `run-rhino-estimate`: validate → summarize-layers → (既存があれば)update / (無ければ)init mapping
  → estimate-by-layer → estimate_summary → `rhino_estimate_report.md` を一括実行。
  **既存 mapping は上書きせず**、新規レイヤーだけ追加した `layer_mapping_updated.csv` を別に出す。
  必須ヘッダー不足のときのみ停止し、それ以外は未確定項目を needs_review で出して続行。
- `audit-rhino-geometry`: 見積前の作図品質を error/warning/info で洗い出し `rhino_geometry_audit.md` に出力。
  （空レイヤー名/重複id/ゼロ形状/開いた曲線の板材候補/曲線長0/閉Brep体積0/極小・極大/単位換算/補助線/注釈/Block）

## 8. 次フェーズ: Rhino本体からのCSV出力

Phase R2 で Rhino から `rhino_objects.csv` を直接出力するスクリプトを用意する。

- 方式: Rhino の **ScriptEditor（CPython 3 / RhinoCommon）** もしくは **rhino3dm**（ファイル直読み）。
  - レイヤー走査: `doc.Layers`、各オブジェクト `doc.Objects` を `obj.Attributes.LayerIndex` で集計。
  - 面積: `AreaMassProperties.Compute(brep/surface).Area`（mm²）。
  - 体積: `VolumeMassProperties.Compute(brep).Volume`（mm³）。閉じた Brep のみ。
  - 曲線長: `curve.GetLength()`（mm）。
  - 種別フラグ: `is_curve / is_closed_curve / is_surface / is_closed_brep / is_mesh` を
    `ObjectType` と各オブジェクトのプロパティから判定。
  - bounding box: `obj.Geometry.GetBoundingBox(True)` の各辺長。
  - 単位系: モデル単位が mm でない場合は `doc.ModelUnitSystem` でスケール換算して mm に正規化。
- 出力ヘッダーは本ツールの `rhino_objects.csv` スキーマに一致させ、UTF-8 with BOM で書く。
- これにより本ツールの `summarize-layers` 以降がそのまま使える（CSV契約で疎結合を維持）。

## 消費税（Phase R6.2）

- `estimate_result.csv` / `estimate_summary.csv` は税抜を基準に出力し、
  `*_ex_tax`（税抜）/`tax`（消費税）/`*_inc_tax`（税込）を併記。`mapping` の `unit_price` は税抜。
- `run-rhino-estimate --tax-rate 0.10` で税率指定。`estimate_summary.csv` の `TOTAL` 行が
  税抜合計/消費税/税込合計。ユーザー向けに `what_costs_how_much.csv`（税込見やすく）を同時出力。
- 内部は税抜計算→最後に1回だけ加税（二重課税防止）。詳細は `docs/tax-handling.md`。
