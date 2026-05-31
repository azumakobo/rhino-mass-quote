# 候補単価選択UI ガイド（Phase R5）

最終更新: 2026-05-31

## 1. UIを作る理由

`layer_mapping.csv` をExcelで直接編集すると、候補単価（`toko_candidate_price_summary.csv` /
`layer_mapping_price_suggestions.csv`）を別途見比べる手間がかかり、加工品単価を誤って
生材単価に使う事故も起きやすい。UIはレイヤーごとに数量根拠・候補単価・警告を一画面に集約し、
**人間が選んで承認**する操作を最小化する。自動確定はしない。

## 2. 起動方法

```bash
cd ~/Documents/claude/projects/steel-estimator
source .venv/bin/activate
pip install -e ".[ui]"   # 初回のみ（fastapi/uvicorn/jinja2/python-multipart）

python -m steel_estimator.cli mapping-ui --out-dir ./data
# → http://127.0.0.1:8765  （Ctrl+C で停止）
# ポート変更: --host 127.0.0.1 --port 8765
```

UIは out-dir 内の以下を読む（無いものは空表示）:
`layer_summary.csv` / `layer_mapping_updated.csv`(無ければ `layer_mapping.csv`、
既に承認済みがあれば `layer_mapping_approved.csv`) / `layer_mapping_price_suggestions.csv` /
`toko_candidate_price_summary.csv` / `estimate_summary.csv`。

## 3. ダッシュボードの見方（GET /）

- レイヤー数 / mapping済み / 未設定 / needs_review / warning / 候補提案件数
- 候補単価の一致レベル（exact / close / category_only / none）
- 概算合計（estimate_summary があれば）
- 次に編集すべきレイヤー（単価未設定など）一覧
- 「承認保存」「保存後に見積を再実行」「approved CSVダウンロード」ボタン

## 4. レイヤー別編集（GET /layers, /layers/{name}）

各レイヤーで Rhino数量根拠（面積/長さ/体積/個数/種別）と、編集フォーム（enabled /
calc_type / 材質 / 寸法 / unit_price / price_unit / waste_rate / density_g_cm3 /
quantity_override / fixed_amount / price_source / notes）を表示。

「この内容で更新」はメモリ上の作業コピーを更新するだけ（ファイルには書かない）。

## 5. 候補単価の選び方

各レイヤーに対し:
1. `layer_mapping_price_suggestions.csv` の提案（match_level付き）を表示。
2. `toko_candidate_price_summary.csv` から同カテゴリの候補を数件表示
   （優先: exact→close→category_only→同カテゴリ最新→サンプル数多）。

「この候補を反映」を押すと、編集フォームの unit_price / price_unit / price_source /
notes（spec_key・見積日・警告）が**作業コピーに**入る。**この時点では保存しない**。

## 6. warning の見方（安全設計）

次の候補は赤系で強く警告し、反映しても notes に警告を残す:
- candidate_class=processed_item / usable_as_base_price=false（加工品）
- needs_review=true / warning あり / sample_count=1 / 外れ値warning
- match_level=category_only / none

**加工品候補（processed_item）は既定で非表示**。「加工品候補も表示する」トグルで初めて出る。

## 7. processed_item を生材単価に使ってはいけない理由

加工品（曲げ・型切・溶接等）の単価には加工費が含まれ、寸法も変形している。これを生材単価に
使うと材料費を過大評価する。材料費と加工費は分離する（加工費は `cost_items.csv` か
`fixed_amount`）。過去に「丸パイプ R曲げ」が生材を汚染した問題と同じ思想。

## 8. 保存されるファイル（POST /save）

- `layer_mapping_approved.csv` … 承認済みmapping（**元の mapping は上書きしない**）
- `layer_mapping_approved_backup_YYYYMMDD_HHMMSS.csv` … 既存approvedがある場合のバックアップ
- `mapping_approval_log.csv` … 変更されたレイヤーの履歴（追記）

approval log の各行: `timestamp, layer_name, old_unit_price, new_unit_price,
old_price_unit, new_price_unit, selected_spec_key, selected_vendor, selected_quote_date,
match_level, confidence, note`。

## 9. 保存後の見積再実行

ダッシュボードに次のコマンドを表示:
```bash
python -m steel_estimator.cli run-rhino-estimate \
  --rhino-csv ./data/rhino_objects.csv \
  --mapping ./data/layer_mapping_approved.csv \
  --cost-items ./data/cost_items.csv --out-dir ./data
```
「保存後に見積を再実行」ボタンは、外部コマンドを起動せず**既存Python関数
`rhino_run.run_rhino_estimate` を直接呼ぶ**（out-dir に rhino_objects.csv がある場合）。

## 10. 既知の限界

- ローカル単一ユーザー前提（認証なし・127.0.0.1）。同時編集は想定しない。
- 編集状態はサーバープロセスのメモリ保持。停止すると未保存の編集は失われる（approvedは残る）。
- 候補は過去・他寸法・他案件の値を含む。最終決定は人間。
- length を含む候補は mapping 側に部材長が無く exact 一致しにくい（close中心）。

## 11. 次フェーズ

- R6-A: Rhino からCSV出力→見積→UI起動をボタンで呼ぶ。
- R6-E: 実見積金額を入力し、ツール概算との差分・誤差原因を記録するUI。
- 承認の差し戻し（approved→特定バックアップへ復元）UI。

## 消費税表示（Phase R6.2）

- `mapping-ui --tax-rate 0.10`（既定0.10）。ダッシュボードに税抜・消費税・税込合計を表示。
- 候補単価は税抜・税込を併記（例: 270円/kg 税抜 → 297円/kg 税込）。
- **保存される `layer_mapping_approved.csv` の `unit_price` は税抜のまま**（二重課税防止）。
  税込は表示専用。詳細は `docs/tax-handling.md`。
