# 候補単価マスター 設計方針（Phase R4）

最終更新: 2026-05-31

## 1. なぜ PDF DB をそのまま使わず候補単価マスターを作るのか

PDF解析DB（`steel_quotes.sqlite` / `extracted_materials.csv`）には、生材・型切・曲げ・丸切・
窓枠・多分割加工品・H形鋼などが**混在**している。これをそのまま Rhino 見積の単価候補に使うと、
加工費込み単価を生材単価として拾う危険がある（実際に「丸パイプ R曲げ」が生材 round_pipe に
混入し加工費込み12,590円が生材2,100円を上書きした問題があった）。

そこで PDF DB と Rhino 見積の間に「候補単価マスター」を挟み、

- 生材単価 / 加工品単価 / 板材 / JIS要マスター / 不明 に**分類**し、
- 同一規格を `spec_key` で**集約**し（最新/中央値/平均/最小/最大）、
- 各候補に**根拠（PDF・見積日・業者・信頼度・レビュー要否）**を必ず付ける。

候補はあくまで「人間が選ぶための提示」。自動確定はしない。

## 2. 生材単価と加工品単価を分離する理由

加工品（曲げ・型切・溶接等）の単価には加工費が含まれ、寸法も変形している。これを生材単価として
使うと材料費を過大評価する。材料費（material）と加工費（processing 等）は estimate_summary でも
別カテゴリに集計しており、同じ思想を単価マスターにも適用する。

## 3. candidate_class の定義

| class | 内容 | usable_as_base_price |
|---|---|---|
| base_material | 丸パイプ直管・角パイプ・FB・丸棒・角棒・アングル等の生材 | true |
| plate_material | 鉄板・鋼板（型切/切板等が混ざるため confidence は慎重） | true |
| processed_item | 曲げ・R曲げ・型切・丸切・窓枠・溶接・加工・巻・ロール・一式 等 | false |
| jis_shape_needs_master | H形鋼・チャンネル（JIS規格表・重量表が必要） | false |
| unknown | 判定不能 | false |

判定順: JIS判定 → 加工語判定（除外） → plate → base カテゴリ → unknown。
**加工品は削除せず** `processed_item` として残す（根拠を保持し、後で参照できるように）。

加工語（含まれたら生材から除外）: 曲げ / R曲げ / L曲げ / 3方曲げ / 型切 / 丸切 / 切板 /
窓枠 / 枠 / 溶接 / 加工 / 孔 / 穴 / レーザー / シャーリング / 曲 / 巻 / ロール / 多分割 /
組立 / 製作 / 一式。

## 4. spec_key / normalized_spec の設計

同一材料を集約するための正規化キー。`spec_key = 'category|grade|tok1|tok2|...'`。

| category | tokens | 例 spec_key | 例 normalized_spec |
|---|---|---|---|
| round_pipe | D{径} t{厚} L{長} | `round_pipe\|STK400\|D48.6\|t2.3\|L6000` | `STK400_D48.6_t2.3_L6000` |
| square_pipe / angle | {W}x{H} t{厚} L{長} | `square_pipe\|STKR400\|50x50\|t2.3\|L6000` | `STKR400_50x50_t2.3_L6000` |
| round_bar | D{径} L{長} | `round_bar\|S45C\|D50\|L1000` | `S45C_D50_L1000` |
| flat_bar | t{厚} W{幅} L{長} | `flat_bar\|SS400\|t6\|W50\|L5500` | `SS400_t6_W50_L5500` |
| plate | t{厚} (+{幅}x{高}) | `plate\|SS400\|t6` | `SS400_PL_t6` |

注: plate は `normalized_spec` のみ `PL` を含め、`spec_key` には含めない（仕様準拠）。
寸法が欠ける場合は token を省き、`needs_review=true` にする。

## 5. 集約ロジック

`spec_key` 単位で集約し、`toko_candidate_price_summary.csv` に出力:
- latest_unit_price / latest_quote_date / latest_source_pdf（quote_date 最大）
- median / average / min / max / sample_count

Rhino見積で使う第一候補は基本 **latest_unit_price**。

## 6. 外れ値検出（warning）

- max/min ≥ 2.0（価格レンジが広い）
- 最新単価が中央値から ±50%以上乖離
- sample_count == 1（サンプル1件のみ）
- 要確認レコード（needs_review）を含む

これらは止めずに warning を付け、人間の確認を促す。

## 7. layer_mapping への提案方法

`suggest-prices-for-mapping` が各レイヤーに候補を当てる（`layer_mapping_price_suggestions.csv`）。

match_level:
- exact: category一致＋（grade一致 or 双方空）＋比較対象の断面寸法が全一致
- close: 断面寸法が15%以内
- category_only: カテゴリのみ一致
- none: 候補なし

提案対象は `usable_as_base_price=true`（生材/板材）のみ。加工品・JIS要マスターは提案しない。

## 8. 自動反映しない理由

- 候補は過去・他寸法・他案件の値を含み、誤差や外れ値がある。
- レイヤーと規格の対応は人間の判断（同じ「角パイプ」でも肉厚・材質が違う）。
- 材料費と加工費の混入を最終的に防ぐのは人間のレビュー。

そのため R4 では `--apply` を実装せず、提案CSVに出すだけ。`layer_mapping.csv` 本体は変更しない。

## 9. 実務上の限界

- vendor 抽出が空のPDFが一定数あり、`--vendor 東鋼材` ではそれらが拾えない（R1抽出の限界）。
- plate はこのデータでは型切/切板が多く、生の鉄板（plate_material）は少ない。
- length を含む spec_key は、mapping 側に部材長が無いため exact 一致しにくい（close/category_only中心）。
- JIS形鋼（H形鋼/チャンネル）の重量・単価は別マスターが必要（Phase R5-B）。

## 10. 将来: 手動承認UIへ

Phase R5-A で、候補単価を画面に並べて人間が選び `layer_mapping` に反映する承認UIへ進める。
本フェーズの CSV（candidate / summary / suggestions）はそのUIの入力データになる。

## 消費税（Phase R6.2）

- `toko_practical_price_master.csv` / `plate_reference_price.csv` /
  `plate_reference_summary_by_thickness.csv` の既存単価列は**税抜**。
- `tax_rate` と `*_ex_tax / *_tax / *_inc_tax` 列を追加。`*_inc_tax` が税込標準値。
- 内部計算は税抜基準、税率初期値 10%（`--tax-rate` で変更可）。詳細は `docs/tax-handling.md`。

## 価格レンジマスター（Phase R6.3）

- `build-price-range-masters` で `plate_price_range_master.csv`（板厚別）と
  `steel_shape_price_range_master.csv`（種別・寸法別）を生成。
- 各行に min/median/average/max を ex/inc で出し、**recommended=median（通常見積）/
  conservative=max（安全側見積）** を提示。`default_pricing_mode=median`、`editable=true`。
- layer_mapping に `pricing_mode`（manual/median/conservative/latest/average）・
  `manual_unit_price`・`recommended_unit_price`・`conservative_unit_price`・
  `selected_unit_price`・`selected_price_basis`・`price_range_source` を追加。
  **unit_price は税抜の selected 値**で互換維持。
- 見積では `what_costs_how_much.csv` / `estimate_summary.csv` に
  recommended/conservative/selected の金額・小計を併記。型切・切板は参考値として継続利用。
