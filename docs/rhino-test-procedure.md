# Rhinoテスト手順（公開版・Phase RC2）

Rhino 8 (Mac) で実モデルから見積まで通すための手順。**実PDF・実単価DB・取引先名・見積日は
一切使わず**、`public_reference_data/` の匿名化・集約・10円単位切上げ済み参考価格だけで動く。

> 公開用参考価格は概算用。**実取引価格ではない**。実発注前に必ず実見積で確認すること。

> **標準方針(2026-05-31〜): 鋼材はポリサーフェス（閉じた押し出し）で作り、体積→重量→kg単価
> （`volume_to_weight`）で見積もる。** 中心線カーブ方式は補助・旧仕様。詳細は
> `docs/rhino-workflow.md` / `docs/pricing-method.md`。

## 0. 準備

```bash
cd <repo>
python -m venv .venv && source .venv/bin/activate
pip install -e ".[ui]"
```

## 1. Rhinoでデモモデルを作る（任意）

手元の実3dmで試してもよいが、公開デモ用に合成モデルを生成できる。

1. Rhino 8 で新規ドキュメントを開く（モデル単位 mm 推奨）。
2. `_ScriptEditor` を開き、言語を **Python 3 (CPython / RhinoCommon)** にする。
3. `rhino_scripts/create_demo_rhino_model.py` を開いて **Run**。
   次のレイヤー・形状が作られる:
   - `PL_SS400_t6` … 1000×500mm の閉平面矩形（板）
   - `SQPIPE_STKR_100x50_t2.3` … 中心線 6000mm
   - `PIPE_STK400_D101.6_t3.2` … 中心線 6000mm
   - `FB_SS400_50x4.5` … 中心線 3000mm
   - `ANGLE_SS400_40x40_t3` … 中心線 3000mm
   - `BOLT_TEST` … 点6個（購入部品）
   - `IGNORE_GUIDE` … 補助線（ignore）

> 寸法は `public_reference_data` の参考価格に一致する規格を選んでいるので、デモで必ずmatchする。

## 2. CSVを出力する

1. ScriptEditor で `rhino_scripts/export_rhino_objects.py` を **Run**。
2. 保存先を `./data/rhino_objects.csv` にする（未保存ならDesktop）。

> Rhinoが手元に無い場合は、同梱の `samples/rhino_objects_demo.csv` をそのまま使える。

## 3. 公開参考単価で一括見積

```bash
python -m steel_estimator.cli estimate-public-rhino \
  --rhino-csv ./data/rhino_objects.csv \
  --out-dir ./public_demo_output --tax-rate 0.10
```

出力（`public_demo_output/`）:
- `layer_summary.csv` … レイヤー集計
- `layer_mapping_initial.csv` … 自動推定の初期mapping
- `layer_mapping_enriched.csv` … 公開参考単価で補完したmapping（元は非上書き）
- `estimate_result.csv` / `estimate_summary.csv` … 見積明細・小計（税抜/税込）
- `what_costs_how_much.csv` … 「何がいくらか」一覧
- `public_rhino_estimate_report.md` … レポート（matched/unmatched・合計・注意）

## 4. 結果を確認する

`what_costs_how_much.csv` と `public_rhino_estimate_report.md` を開く。
- 税抜合計 / 消費税 / 税込合計
- recommended（中央値相当） / conservative（最大値相当）
- matchしたレイヤー / matchしなかったレイヤー

## 5. mapping UI で単価・モードを修正（任意）

```bash
python -m steel_estimator.cli mapping-ui --out-dir ./public_demo_output \
  --public-reference ./public_reference_data
# http://127.0.0.1:8765
```
UI上で recommended / conservative / manual を選び、pricing_mode・manual_unit_price を調整。
**保存は `layer_mapping_approved.csv`**（元mappingは上書きしない）。単価は税抜で保存、税込は表示のみ。

## 6. 承認済みmappingで再見積

```bash
python -m steel_estimator.cli run-rhino-estimate \
  --rhino-csv ./data/rhino_objects.csv \
  --mapping ./public_demo_output/layer_mapping_approved.csv \
  --out-dir ./public_demo_output
```

## 誤差が出たときの分類（実見積と比較する場合）

レイヤー割当ミス / 単価ミス / 面積取得ミス（板が閉じていない）/ パイプ長さ取得ミス（中心線が無い）/
ブロック未展開 / 加工費不足 / 板取り未考慮 / 塗装・運搬・施工費不足。

## 既知の限界

- 面積/長さ/体積の正確さは Rhino 作図品質に依存。
- ブロック(InstanceObject)は未展開（内部数量を集計しない）。
- 公開参考価格は実取引価格ではない。matchは参考。最終確認は人間。
- アングル/チャンネル/H形鋼の重量はJIS表が必要なため、参考は m単価・本単価が中心。

## 実機テストの状況

本手順は **コードとサンプルCSV(`samples/rhino_objects_demo.csv`)で自動検証済み**
（`estimate-public-rhino` が 5レイヤーmatch・税抜/税込・recommended/conservative を出力）。
**Rhino 8 本体での手動実行（create_demo / export スクリプトのGUI実行）は本環境では未検証**。
ScriptEditor上の挙動は環境差がありうるため、実機で確認のうえ必要なら微修正すること。
