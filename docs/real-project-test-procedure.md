# 実案件テスト手順（Phase R3 検証）

実際の `.3dm` から出力したCSVで見積を行い、実見積との差分を記録して精度と
運用フローを検証するための手順。`data/` は gitignore 済みなので実データ置き場に使う。

## 手順

1. Rhino で対象の `.3dm` を開く。
2. `export_rhino_objects.py` を ScriptEditor で実行（`docs/rhino-quickstart.md` 参照）。
3. 出力CSVを `data/rhino_objects.csv` として保存する。
4. 一括実行する:
   ```bash
   python -m steel_estimator.cli run-rhino-estimate \
     --rhino-csv ./data/rhino_objects.csv \
     --mapping ./data/layer_mapping.csv \
     --cost-items ./data/cost_items.csv \
     --out-dir ./data
   ```
5. `data/layer_mapping_updated.csv`（初回は `layer_mapping.csv`）を開き、
   `rhino_estimate_report.md` の未設定レイヤーを中心に calc_type / 寸法 / unit_price を埋める。
6. 単価を埋めた mapping を `--mapping` に渡して再度 `run-rhino-estimate` を実行する。
7. `data/estimate_result.csv` と `data/estimate_summary.csv` を確認する。
8. **実見積（実際に業者から取った見積）との差分を記録する**。
   - 項目ごとに「本ツール概算」「実見積」「差額」「差率」を表にする。

## 9. 誤差原因の分類

差分が出たら、原因を以下に分類して記録する（次フェーズの改善対象になる）。

| 分類 | 例 | 対処の方向 |
|---|---|---|
| レイヤー割当ミス | 板材なのに別レイヤー | レイヤー整理 / mapping修正 |
| 単価ミス | 古い単価・桁違い | unit_price更新 / PDF DB参照 |
| 面積取得ミス | 開いた曲線で面積0 | 閉じた平面曲線に修正（audit警告） |
| パイプ長さ取得ミス | 中心線が無い/分断 | 中心線レイヤーを整備 |
| ブロック未展開 | InstanceObject内の数量 | Phase R4-B で展開対応 |
| 加工費不足 | 曲げ・溶接・切断の計上漏れ | cost_items.csv に追加 |
| 板取り未考慮 | 歩留まり・端材 | waste_rate調整 / Phase R4-F |
| 塗装・運搬・施工費不足 | 諸経費の計上漏れ | cost_items.csv に追加 |

## 記録テンプレート（コピーして使う）

```
案件名:
3dmファイル:
実行日:
本ツール概算合計(税別): ¥
実見積合計(税別): ¥
差額: ¥ / 差率: %

主要差分:
- 項目 / 概算 / 実見積 / 差額 / 原因分類
- ...

気づき・改善案:
- ...
```

## 既知の限界（テスト時に念頭に置く）

- 面積/長さ/体積の正確さは Rhino 作図品質に依存（閉じているか・平面か・中心線か）。
- Block は未展開（内部数量は集計されない）。
- 板取り（ネスティング）最適化は未実装。面積×板厚の単純重量。
- 穴あけ・溶接長・塗装面積は未集計（別フェーズ）。
- アングル/チャンネル/H形鋼の重量はJIS表未搭載 → 単価指定で代替。
