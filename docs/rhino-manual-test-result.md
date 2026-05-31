# Rhino 8 実機テスト結果（記録）

> 公開用参考価格は概算用で、実取引価格ではない。本記録はデモモデルでのフロー確認。

## 実行環境

- 実行日: 2026-05-31（レポート timestamp 2026-05-31 03:54:40）
- macOS version: （ユーザー環境。未記入＝後で追記可）
- Rhino version: Rhino 8（Mac）
- Python mode: Python 3 (CPython / RhinoCommon)
- モデル単位: Millimeters（出力に単位換算warningなし＝mmで実行）

## 実機由来であることの確認（重要）

`data/rhino_objects.csv` は **実際の Rhino 8 実行による出力**であることを以下で確認:

- `object_id` が実GUID（例 `37e7d336-c0c7-42ce-bf8f-c76474d33a2c`）。サンプルの `p1/s1` ではない。
- `BOLT_TEST` が **点6個＝6行**（各 object_count=1）。サンプルCSVは1行 count=6 だったので別物。
- 総行数 **12**（曲線6＋点6）。サンプルは7行。集計どおり レイヤー数7・面積取得1・曲線長取得6。
- `PL_SS400_t6` は閉平面曲線で area=500000mm²・周長3000mm を取得。
- `file_name = unsaved.3dm`：新規ドキュメントを保存せず export したため、出力はフォールバック
  （モデル同階層が無いので Desktop か指定先）。動作上の問題なし。

## 1. create_demo_rhino_model.py
- 結果: **成功**（7レイヤー作成。ScriptEditorでRun）

## 2. export_rhino_objects.py
- 結果: **成功**
- 出力CSV: `./data/rhino_objects.csv`（file_name=unsaved.3dm）
- オブジェクト数 / レイヤー数: **12 / 7**
- 面積取得 / 曲線長取得 / 体積取得: **1 / 6 / 0**

## 3. validate-rhino-csv
- 結果: **OK**
- 行数: 12 / レイヤー数: 7 / 面積取得: 1 / 曲線長取得: 6
- error / warning: なし（zero-geometryはBOLTの点6個のみで閾値内）

## 4. estimate-public-rhino
- match件数: **5**（PL / SQPIPE / PIPE / FB / ANGLE）
- unmatched件数: **0**
- needs_review件数: **1**（BOLT_TEST＝公開価格に該当なし）
- ignored: **IGNORE_GUIDE**
- 税抜合計 / 消費税(10%) / 税込合計: **¥18,758 / ¥1,876 / ¥20,634**
- recommended税込 / conservative税込: **¥20,634 / ¥21,696**

### 何がいくらか（what_costs_how_much.csv）
| レイヤー | カテゴリ | 数量 | 単価(税抜) | 税込金額 | 出典 |
|---|---|---|--:|--:|---|
| PL_SS400_t6 | plate | 23.55kg(0.5m²×t6) | ¥270/kg | ¥6,994 | plate_range SS400 t6 |
| PIPE_STK_D48.6_t2.3 | round_pipe | 1本 | ¥4,550/stock | ¥5,005 | shape_range |
| SQPIPE_STKR_40x40_t2.3 | square_pipe | 1本 | ¥4,240/stock | ¥4,664 | shape_range |
| ANGLE_SS400_40x40_t3 | angle | 1本 | ¥1,850/stock | ¥2,035 | shape_range |
| FB_SS400_50x4.5 | flat_bar | 1本 | ¥1,760/stock | ¥1,936 | shape_range |

## 5. 出力ファイル
- `public_demo_output/what_costs_how_much.csv` … 生成 ✅
- `public_demo_output/public_rhino_estimate_report.md` … 生成 ✅
- `public_demo_output/layer_summary.csv` / `layer_mapping_initial.csv` /
  `layer_mapping_enriched.csv` / `estimate_result.csv` / `estimate_summary.csv` … 生成 ✅

## 6. 発生したエラーと修正
- なし（create_demo / export / validate / estimate すべて初回で成功）。

## 7. 残課題
- 実機で `_Units` が m など mm以外の場合の挙動は本テストでは未確認（mmで実行）。
- ブロック(InstanceObject)を含むモデルは未テスト（v1は未展開仕様）。
- 板取り・加工費・塗装/運搬費は別フェーズ。

## 8. 判定
- **Rhino 8 Mac で デモモデル作成 → CSV出力 → 公開参考価格のみで見積、までのフロー動作確認済み**。
- 成功判定（match5 / needs_review=BOLT / ignored=GUIDE / what_costs・report生成）すべて充足。
