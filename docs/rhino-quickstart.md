# Rhino クイックスタート（Mac / Rhino 8）

Rhinoモデルから概算見積までを最短手順で行うためのガイド。

## 0. 補助スクリプト

プロジェクト直下の `scripts/` に2つの補助スクリプトがあります。

```bash
# Rhino を起動し、export_rhino_objects.py のパスをクリップボードへコピー＋手順表示
bash scripts/open_rhino_export_helper.sh

# Rhino を起動せず、export_rhino_objects.py のパスだけクリップボードへコピー
bash scripts/copy_rhino_script_path.sh
```

> **未検証事項**: Rhino 8 Mac版で「ScriptEditorに特定スクリプトを自動で開く／Runする」
> までを CLI から自動化する確実な方法は未検証です。本スクリプトは Rhino.app の起動と
> スクリプトパスの受け渡しまでを確実に行い、ScriptEditor内の操作は下記の手動手順で行います。
> （Rhino の `_RunPythonScript` にフルパスを渡す運用も可能ですが、環境差があるため手動を推奨）

## 1. Rhino でCSVを出力する

1. Rhino 8 で対象の `.3dm` を開く。
2. コマンド: `_ScriptEditor` を実行。
3. 言語を **Python 3 (CPython / RhinoCommon)** にする。
4. `File > Open` で `export_rhino_objects.py`（クリップボードのパス）を開く。
5. **Run（▶）**。保存先を選ぶ（推奨: プロジェクトの `data/rhino_objects.csv`）。
6. 出力後、コマンドラインに件数サマリが表示される。

## 2. 見積を一括実行する

```bash
cd ~/Documents/claude/projects/steel-estimator
source .venv/bin/activate

# 任意: 作図品質を先に監査
python -m steel_estimator.cli audit-rhino-geometry \
  --input ./data/rhino_objects.csv --out ./data/rhino_geometry_audit.md

# 一括実行（検証→集計→mapping→見積→レポート）
python -m steel_estimator.cli run-rhino-estimate \
  --rhino-csv ./data/rhino_objects.csv \
  --mapping ./data/layer_mapping.csv \
  --cost-items ./data/cost_items.csv \
  --out-dir ./data
```

## 3. mapping を編集して再実行

1. `data/rhino_estimate_report.md` の「未設定レイヤー一覧」を見る。
2. `data/layer_mapping.csv`（初回）または `data/layer_mapping_updated.csv`（2回目以降）を開く。
3. 未設定レイヤーの `calc_type` / 寸法 / `unit_price` / `density_g_cm3` を埋める。
   - 編集した updated を次回の `--mapping` に渡せば、その内容が保持される。
4. 加工費・運搬費は `data/cost_items.csv` に追加。
5. もう一度 `run-rhino-estimate` を実行し、`estimate_result.csv` / `estimate_summary.csv` を確認。

> 既存 mapping は **上書きされません**。新規レイヤーだけが `layer_mapping_updated.csv` に追記されます。

## 4. レイヤー設計のコツ

- 鉄板は閉じた平面曲線／サーフェスで（面積が取れる）→ area_to_weight。
- パイプ・アングルは中心線カーブを専用レイヤーに → curve_length_to_stock / _meter。
- ソリッドは閉じた Brep → volume_to_weight。
- ボルト・金物は点やブロック → object_count。
- 補助線・注釈は ignore（出力はされる）。
