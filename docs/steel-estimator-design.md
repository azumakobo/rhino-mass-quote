# 鋼材見積PDF解析・概算見積ツール 設計方針

最終更新: 2026-05-31

## 1. 目的

ダウンロード済みの鋼材見積PDFを解析し、丸パイプ・角パイプ・アングル・チャンネル・
フラットバー・鉄板（切板/型切）・丸棒・H形鋼などの情報を構造化して保存する。
将来的に材料リスト（material_request.csv）から過去単価・重量計算に基づく概算見積を出す。

### 原則
- **完全ローカル処理**。外部APIにPDF内容・取引先情報を送信しない。
- 初期段階は完璧な自動化より、**抽出結果を確認・修正できる堅牢な基盤**を優先。
- 機微情報（取引先名・単価）を含むため、原本PDF・抽出DB・見積データはGit管理外。

## 2. 入力データの実態（2026-05-31 調査結果）

対象: `/Users/azumakobo/akiyama_quotes/` に 231 PDF。

- すべて**テキストPDF**（PDF-1.7, StructTreeRoot 付き）。現時点でOCR不要。
- 発行元はほぼ単一業者「**東鋼材（担当: 秋山）**」、宛先「あずま工房 東 弘一郎 様」。
- 各PDF 1ページ、**統一テーブル**を持つ。`pdfplumber.extract_tables()` でクリーンに取得可能。

### 共通テーブル列（東鋼材フォーマット）
```
No. | 品番 | 細番 | 材質 | 形状 | 板厚 | 寸1 | 寸2 | ＱＴＹ | 金額/個 | 金額/台 | 備考
```

- 見積日: ページ先頭行 `2022/12/14` 形式。
- 有効期限・消費税注記・業者名は本文テキストに混在。

### 重要: 列の意味は「形状」で変わる
`板厚 / 寸1 / 寸2` の物理的意味は形状依存。特に丸モノは **板厚列にφ径が入る**。

| 形状 | category | 板厚列 | 寸1列 | 寸2列 | 例 |
|------|----------|--------|-------|-------|----|
| アングル | angle | 脚厚 thickness_mm | `40x40` = width×height | 長さ length_mm | `3 / 40x40 / 5500` |
| 角パイプ | square_pipe | 肉厚 thickness_mm | `40x40` = width×height | 長さ length_mm | `2.3 / 40x40 / 6000` |
| FB | flat_bar | 厚 thickness_mm | 幅 width_mm | 長さ length_mm | `6 / 50 / 5500` |
| 切板 | plate | 厚 thickness_mm | plate_width_mm | plate_height_mm | `4.5 / 300 / 300` |
| 型切 | plate(異形) | 厚 thickness_mm | 外接 plate_width_mm | 外接 plate_height_mm | `12 / 468 / 842.5` |
| 丸パイプ | round_pipe | **φ外径 diameter_mm** | 肉厚 thickness_mm | 長さ length_mm | `φ76.3 / 3.2 / 500` |
| 丸棒 | round_bar | **φ径 diameter_mm** | (空) | 長さ length_mm | `φ50 / / 1000` |
| H形鋼 | h_beam | `100x100` = H×B | `6/8` = web/flange厚 | 長さ length_mm | `100x100 / 6/8 / 3000` |
| ロール巻き | rolled | **φ径 diameter_mm** | 板厚 thickness_mm | 高さ length_mm | `φ508 / 3.2 / 2000` |

観測された材質: `SS400, STKR, STKMR, STK400, SGP, SUS304, S45C, A5052`。
（A5052/アルミは鋼材ではないが見積に混在 → grade に保持、密度計算は鉄前提なので notes 警告）

## 3. 抽出アーキテクチャ（2経路）

1. **テーブル経路（主・高信頼）**: 東鋼材フォーマットを列マッピングで解釈。
   ヘッダー行を検出し、形状ごとの意味マップで各フィールドへ。confidence 高。
2. **フリーテキスト経路（従・フォールバック）**: 表が取れないPDF向け。
   正規表現で行から `category / grade / 寸法` を抽出。仕様の寸法例
   （`φ48.6×t2.3×6000`, `□50×50×2.3×6m`, `L-50×50×6`, `PL 6×914×1829`, `SS400 t9 4×8`）に対応。
   曖昧（例: `4×8` 尺表記疑い）は `needs_review=True`。

両経路とも `material_parser` の分類器・数値正規化を共有する。

## 4. 材料分類カテゴリ

| category | キーワード/トークン |
|----------|---------------------|
| round_pipe | 丸パイプ, 丸鋼管, STK, φ, Φ, パイプ |
| square_pipe | 角パイプ, 角鋼管, □, BOX, STKR |
| angle | アングル, Lアングル, 等辺山形鋼, L- |
| channel | チャンネル, Cチャン, 溝形鋼, C- |
| flat_bar | フラットバー, FB, 平鋼 |
| plate | 鉄板, 鋼板, PL, プレート, SS400板, 縞鋼板, 切板, 型切 |
| round_bar | 丸棒, 丸鋼, RB |
| square_bar | 角棒, 角鋼 |
| h_beam | H形鋼, H鋼（仕様外だが頻出のため追加） |
| rolled | ロール巻き（カスタム加工。重量参照は単価優先） |
| unknown | 分類不能 |

## 5. データモデル（抽出フィールド）

`source_pdf_path, source_pdf_filename, page_number, raw_text_line, vendor_name, quote_date,
item_name_original, material_category, material_grade, shape_token, dimension_text_original,
diameter_mm, width_mm, height_mm, thickness_mm, length_mm, plate_width_mm, plate_height_mm,
quantity, unit, unit_price, amount, currency, confidence, needs_review, notes`

## 6. 保存

- SQLite（`data/steel_quotes.sqlite`）+ CSV エクスポート。
- テーブル `materials`（抽出1行=1レコード）。再取り込み時は source_pdf + page + 行ハッシュで重複回避。
- `export-review` で `needs_review` 優先のレビュー用CSVを出力。

## 7. 概算見積エンジン（v1）

- 過去PDF抽出の「過去単価」を材料マスターとして使用。単価には必ず `quote_date` と `vendor_name` を紐付け。
- 同一材料に複数単価 → 最新 / 中央値 / 平均 / 最高 を算出可能に。
- 精度区分:
  - `exact`: 同一カテゴリ・規格・寸法・長さの過去見積あり
  - `close`: 同一カテゴリ・近似寸法の過去見積あり
  - `formula`: 重量計算 × kg単価で推定
  - `unknown`: 根拠不足
- 材料費と加工費（切断・穴あけ・溶接・塗装）・送料・消費税は**混ぜない**。v1は材料費のみ。

### 重量計算
- 鉄密度 初期値 **7.85 g/cm³**。
- 実装: 丸パイプ・角パイプ（中空）・鉄板・丸棒。
- アングル/チャンネルはJIS表照合が必要 → v1は過去単価参照優先、近似式は notes に「概算」明記。
- 後続でJIS規格マスターを追加できる構成。

## 8. CLI

```
python -m steel_estimator.cli ingest --pdf-dir ./quotes --out ./data/extracted_materials.csv
python -m steel_estimator.cli ingest --pdf-dir ./quotes --db ./data/steel_quotes.sqlite
python -m steel_estimator.cli export-review --db ./data/steel_quotes.sqlite --out ./data/review.csv
python -m steel_estimator.cli estimate --input ./data/material_request.csv --db ./data/steel_quotes.sqlite --out ./data/estimate_result.csv
```

## 9. 実装フェーズ

- **Phase 1**: PDFテキスト抽出 / 行単位材料候補抽出 / 正規表現分類 / CSV出力 / テスト
- **Phase 2**: SQLite保存 / vendor・date抽出 / 過去単価検索 / review.csv
- **Phase 3**: 重量計算 / kg単価推定 / material_request → estimate_result.csv
- **Phase 4**: 簡易Web UI（FastAPI+React/Next.js）/ アップロード / 人間レビュー / マスター編集
- **Phase 5**: OCR（pytesseract+pdf2image）/ JIS規格マスター / 加工費・歩留り・端材率 / 価格上昇率分析

本実装は Phase 1–3 の基盤を一体で提供する（テーブル経路により実データで即運用可能）。

## 10. 既知の限界

- 重量式は鉄前提。SUS/アルミは密度警告のみ（v1は単価参照優先）。
- 型切（異形）の寸1/寸2は外接矩形であり実面積ではない → needs_review。
- H形鋼/チャンネルの重量近似はJIS表未搭載のため未実装（単価参照のみ）。
- 単一業者データのため、他社フォーマットはフリーテキスト経路の精度に依存。
