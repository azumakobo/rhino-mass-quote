# Rhino エクスポートスクリプト利用ガイド（Phase R2）

最終更新: 2026-05-31

`rhino_scripts/export_rhino_objects.py` は、Rhino 8 で開いているモデルから
steel-estimator 互換の `rhino_objects.csv` を出力するスクリプトです。

## 1. Rhino でスクリプトを実行する

1. Rhino 8 で対象の `.3dm` を開く。
2. コマンドラインに `_ScriptEditor` と入力して ScriptEditor を起動。
   （または `_RunPythonScript` で本ファイルを直接指定してもよい）
3. ScriptEditor の言語を **Python 3 (CPython / RhinoCommon)** にする。
4. `File > Open` で `rhino_scripts/export_rhino_objects.py` を開く。
5. **Run（▶）** を押す。
6. 保存ダイアログが出たら出力先を選ぶ。出ない環境では次の順で自動決定:
   1) モデルと同じフォルダの `rhino_objects.csv`
   2) モデル未保存なら Desktop の `rhino_objects.csv`
7. 実行後、出力パス・オブジェクト数・レイヤー数・面積/体積/曲線長の取得件数・
   notesあり件数・モデル単位がコマンドラインに表示される。

> 全レイヤー・全オブジェクトを出力します（補助線・注釈も除外しません）。
> 何を見積もり何を無視するかは後段の `layer_mapping.csv` で決めます。

## 2. 出力後に実行するコマンド

```bash
# 0) （任意）出力CSVの妥当性を検証
python -m steel_estimator.cli validate-rhino-csv --input ./data/rhino_objects.csv

# 1) レイヤー集計
python -m steel_estimator.cli summarize-layers --input ./data/rhino_objects.csv --out ./data/layer_summary.csv

# 2) mapping 雛形を生成（または既存に追記）
python -m steel_estimator.cli init-layer-mapping   --summary ./data/layer_summary.csv --out ./data/layer_mapping.csv
python -m steel_estimator.cli update-layer-mapping --summary ./data/layer_summary.csv --mapping ./data/layer_mapping.csv

# 3) layer_mapping.csv を人間が編集（calc_type・寸法・unit_price を確定）

# 4) 概算見積
python -m steel_estimator.cli estimate-by-layer \
    --summary ./data/layer_summary.csv --mapping ./data/layer_mapping.csv \
    --cost-items ./data/cost_items.csv \
    --out ./data/estimate_result.csv --summary-out ./data/estimate_summary.csv
```

## 3. 出力 CSV スキーマ

ヘッダー（既存 `rhino_objects.csv` と完全互換、UTF-8 with BOM）:

`file_name, layer_name, object_id, object_name, object_type, object_count,
object_area_mm2, object_volume_mm3, object_curve_length_mm,
bounding_box_width_mm, bounding_box_height_mm, bounding_box_depth_mm,
is_closed_curve, is_closed_brep, is_surface, is_mesh, is_curve, notes`

- `layer_name`: フルパスを `親::子` 形式で出力（Rhino の FullPath）。
- `object_id`: RhinoオブジェクトのGUID。
- `object_type`: Curve / Brep / Surface / Extrusion / Mesh / Point / Annotation /
  InstanceObject / Other。
- 値が取れない場合は **0 / 空欄**にし、理由を `notes` に記録（エラーで止めない）。

## 4. 単位換算

`doc.ModelUnitSystem` を見て **mm に統一**して出力します。

| モデル単位 | scale_to_mm |
|---|---|
| Millimeters | 1 |
| Centimeters | 10 |
| Meters | 1000 |
| Inches | 25.4 |
| Feet | 304.8 |

- 長さ = `値 × scale`、面積 = `値 × scale²`、体積 = `値 × scale³`。
- 上表にない単位は `scale=1` のまま出力し、`notes` に warning を記録。

## 5. 取得できる形状情報 / できない情報

取得を試みるもの:
- Curve: 曲線長（`GetLength`）、閉曲線判定（`IsClosed`）、**閉じた平面曲線なら面積**。
- Brep/Surface: 面積（`AreaMassProperties`）、ソリッドなら体積（`VolumeMassProperties`）。
- Extrusion: Brep に変換して面積・体積。
- Mesh: 面積、閉メッシュなら体積。
- すべて: バウンディングボックス（`GetBoundingBox(True)`）。

取得しない／できないもの:
- **Block(InstanceObject) は展開しない**（`notes: block instance not expanded`、bboxのみ）。
- Brep のエッジ長は合計しない（パイプ類は**中心線カーブ**で長さ管理する想定のため）。
- 失敗時は 0 とし `notes` に失敗理由。

## 6. レイヤー設計の注意（見積しやすい作り方）

- **鉄板・板材**: 面積が取れる「閉じた平面曲線」または「サーフェス」で作る → `area_to_weight`。
- **パイプ・角パイプ・アングル類**: **中心線カーブ**を専用レイヤーに置く → 長さ集計が楽。
  `curve_length_to_stock`（定尺本数）または `curve_length_to_meter`。
- **ソリッド部品・異形・鋳物的形状**: 閉じた Brep/Mesh → `volume_to_weight`。
- **ボルト・金物・購入品**: 点やブロックで数を表す → `object_count`。
- **補助線・通り芯・注釈・寸法線**: そのまま出力されるが `layer_mapping.csv` で `ignore` に。

## 7. 既知の限界

- ブロックは v1 では展開しない（数量・寸法はブロック内を見ない）。
- 曲げ加工は Rhino 形状だけでは加工費を推定しない（`cost_items.csv` か `fixed_amount`）。
- 板取り（ネスティング）最適化はまだ行わない（面積×板厚の単純重量）。
- 穴あけ数・溶接長・塗装面積は本フェーズでは集計しない（別フェーズ）。
- 面積/長さ/体積の正確さは Rhino 側の作図品質（閉じているか・平面か等）に依存。

## 8. 次フェーズの実装候補

- Block 展開（`InstanceObject` の参照ジオメトリを再帰展開して数量化）。
- 塗装面積（露出サーフェス面積の集計）。
- 溶接長（接合エッジ長の抽出）。
- 穴数（円・円柱開口のカウント）。
- 板取り最適化（既存 linear-cutter 的なネスティングとの連携）。
- Rhino プラグイン化 / UI 化（ボタン一発でエクスポート＋見積呼び出し）。
