# 消費税の扱い（Phase R6.2）

## 原則

- **内部計算は常に税抜(ex_tax)を基準**にする。最後に消費税を加える。
- 元データの税抜単価（`unit_price`, `price_per_kg`, `estimated_amount` 等）は**破壊しない**。
- 税込（`*_inc_tax`）は**表示・標準値**として併記する。根拠単価を税込に置き換えない。
- `layer_mapping` / `layer_mapping_approved` の `unit_price` は**税抜のまま**保持する。
  これにより、見積計算（税抜小計→消費税→税込合計）で**二重課税を防ぐ**。

## 税率

- 初期値 `DEFAULT_TAX_RATE = 0.10`（`src/steel_estimator/settings.py`）。
- 各コマンドの `--tax-rate` で変更可能（例: `--tax-rate 0.08`）。
- `--tax-rate 10` のように%でも受理（内部で 0.10 に正規化）。

## 丸め

- 円未満は **Python標準 `round()`（偶数丸め / banker's rounding）** で処理する。
- 税抜が整数円のとき `inc = ex + tax` が厳密に成立する
  （`round(N*(1+r)) == N + round(N*r)`、N が整数のため）。金額の整合が取れる。
- 単価（円/kg, 円/m² 等）は小数を含みうるため、`tax`/`inc` は各々 `ex` から独立に
  算出して丸める（例: 273.5円/kg → 税27, 税込301）。

## 計算式

- `tax = round(ex × tax_rate)`
- `inc = round(ex × (1 + tax_rate))`

例: SS400 t6 の参考kg単価が税抜 **270円/kg** のとき、税込標準値は **297円/kg**。

## どのCSVに税込カラムを追加したか

| ファイル | 既存（税抜） | 追加（税込関連） |
|---|---|---|
| `toko_practical_price_master.csv` | latest/median/average_unit_price, price_per_m, price_per_kg | `tax_rate` + 各 `*_ex_tax/_tax/_inc_tax` |
| `plate_reference_price.csv` | unit_price, amount, price_per_m2, price_per_kg | `tax_rate` + 各 `*_ex_tax/_tax/_inc_tax` |
| `plate_reference_summary_by_thickness.csv` | latest/median/average price_per_kg, latest/median price_per_m2 | `tax_rate` + 各 `*_ex_tax/_tax/_inc_tax` |
| `estimate_result.csv` | estimated_amount | `estimated_amount_ex_tax`, `tax_rate`, `estimated_tax_amount`, `estimated_amount_inc_tax` |
| `estimate_summary.csv` | subtotal_amount | `subtotal_amount_ex_tax`, `tax_rate`, `tax_amount`, `subtotal_amount_inc_tax`（TOTAL行=total_ex/tax/inc） |
| `what_costs_how_much.csv`（新規） | — | unit_price_ex_tax/inc_tax, estimated_amount_ex_tax/tax/inc_tax |

`layer_mapping_enriched.csv` の `unit_price` は**税抜のまま**。税込は `notes` に
「税込参考: 297円/kg(tax 10%)」として併記する（カラム互換性のため）。

## 二重課税を避ける注意

1. mapping の `unit_price` は税抜。ここに税込を入れない。
2. 見積計算は税抜単価 × 数量 → 税抜小計を出し、**最後に1回だけ**税を加える。
3. enrich が単価を自動補完する場合も**税抜**を入れ、税込は notes 参考のみ。
4. UI（mapping-ui）は税込を見やすく表示するが、保存する `unit_price` は税抜。

## 税抜・税込・税額を分けて確認する方法

- 単価マスター: `*_ex_tax`（税抜）/ `*_tax`（消費税）/ `*_inc_tax`（税込）列を並べて確認。
- 見積: `estimate_summary.csv` の `TOTAL(除ignored)` 行で
  `subtotal_amount_ex_tax` / `tax_amount` / `subtotal_amount_inc_tax` を確認。
- ユーザー向け一覧: `what_costs_how_much.csv`（税込を見やすく、税抜・税額も併記）。

## 対応コマンド（`--tax-rate`）

`analyze-candidate-prices` / `enrich-layer-mapping` / `estimate-by-layer` /
`run-rhino-estimate` / `estimate` / `mapping-ui`。

> 注: `build-candidate-prices`（生の候補抽出）と `suggest-prices-for-mapping`（提案）は
> 税抜の根拠データ/提案を出すため、税込カラムは付与していない（税は下流の分析・見積で付加）。
> `run-real-project-audit` は本リポジトリ未実装（`run-rhino-estimate` が同等機能 + 税対応）。
