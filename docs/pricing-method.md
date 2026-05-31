# 見積計算方式（標準: 体積→重量）

最終更新: 2026-05-31

## 標準方針

このツールの標準Rhino運用では、**鋼材はすべてポリサーフェス（閉じた押し出し / ExtrudeCrv 等）**
として作図する。したがって鋼材の見積は **`volume_to_weight`（体積→重量→kg単価）を標準**とする。

中心線カーブから定尺本数を出す `curve_length_to_stock` / `curve_length_to_meter` は
**補助・旧仕様**として残すが、標準ワークフローでは使わない。

## calc_type の選択ルール（自動推定）

`summarize-layers` / `estimate-public-rhino` の自動推定は次の優先順:

1. **板材 (PL / plate)**
   - 面積が取れる → `area_to_weight`
   - 面積が無く体積があるソリッド板 → `volume_to_weight`
2. **鋼材系**（square_pipe / round_pipe / angle / flat_bar / round_bar / square_bar /
   h_beam / channel、または名前に STEEL/METAL）
   - `total_volume_mm3 > 0` → **`volume_to_weight`（第一候補）**
   - 体積が無く中心線カーブのみ → `curve_length_to_stock`（補助・旧仕様）
   - どちらも無い → 要確認（warning）
3. **補助線・注釈** → `ignore`
4. **購入部品・ボルト** → `object_count`（または `manual_quantity`）

最終決定は人間が `layer_mapping` で確定する（自動推定は候補）。

## volume_to_weight の計算式

```
estimated_weight_kg     = total_volume_mm3 × density_g_cm3 × 1e-6
estimated_amount_ex_tax = estimated_weight_kg × unit_price        # unit_price は税抜・kg単価
price_unit              = kg
estimated_amount_inc_tax = 税処理で算出（二重課税しない）
```

## 密度 density_g_cm3

| 材質 | 密度 |
|---|---|
| SS400 / STK / STKR / 鋼材系 | 7.85 |
| SUS304 | 7.93 |
| A5052 / AL / aluminum | 2.70 |
| 不明 | 7.85 を仮定（warning） |

## kg単価（公開参考価格）

`public_shape_reference_prices.csv` の kg単価を優先採用:
- `recommended_price_per_kg_ex_tax_rounded`（pricing_mode=median）
- `conservative_price_per_kg_ex_tax_rounded`（pricing_mode=conservative）
- `*_inc_tax_rounded` は税込表示用
- `manual_unit_price`（pricing_mode=manual）

注意: **angle / h_beam / square_bar は公開参考に kg単価が無い**（JIS重量表が必要だったため）。
これらはRhinoからRhino体積が取れていれば**重量は算出できる**が、**kg単価が無いと金額は確定できず
`needs_review`** になる。その場合は mapping UI で kg単価を手入力（manual）するか、社内基準を入れる。

## 安全側単価の定義（重要）

**安全側単価**は「最大値」ではなく、**中央値を基準に、最低1.3倍・最大2.0倍の範囲で補正した
概算用単価**です。外れ値による過大な見積りを避けつつ、通常単価より高めに見積もるための値です。

```
median_price = 中央値
max_price    = 最大値
min_safe = median_price × 1.3
max_safe = median_price × 2.0
safe_price = max(max_price, min_safe)      # 最低でも中央値×1.3
safe_price = min(safe_price, max_safe)     # 最大でも中央値×2.0
```
例: 中央値300/最大1420→**600**、300/300→**390**、300/350→**390**、300/500→**500**、300/700→**600**。

注意:
- これは正式見積りではなく、**概算用の補助値**です。
- 市況・ロット・地域・加工条件・仕入れ先によって実単価は変動します。
- 実装は `price_ranges.safe_conservative()`。Quote側ではさらに安全係数×1.2（10円切上）が乗ります。

## pricing_mode

| mode | 採用単価 |
|---|---|
| median | recommended（中央値） |
| conservative | 安全側＝中央値の1.3〜2.0倍へ範囲制限（外れ値抑制。単純な最大値ではない） |
| manual | manual_unit_price（手入力） |

## 方針の維持

- 自動確定はしない。候補提示 → 人間が確定（レビュー可能な概算）。
- 生材単価と加工費（曲げ・切断・溶接・塗装・運搬）は混ぜない。
- 公開参考価格は概算用。実取引価格ではない。発注前に必ず実見積で確認。
