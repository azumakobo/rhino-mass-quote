# データセキュリティ・公開方針（Phase RC1.1）

## 基本方針

- 本ツールは収益化しない。ローカル利用・研究・制作補助・公開OSS的な位置づけ。
- **公開リポジトリには実データを含めない**：実PDF、実見積DB、実CSV、実取引先名、
  見積日、PDF名、`source_page`、`source_pdf`、個別明細、実数量、実金額。
- ただし「何も試せない」状態を避けるため、**匿名化・集約・丸め済みの参考単価**を同梱する。

## ファイルの分離

| 区分 | 例 | Git管理 |
|---|---|---|
| 実データ・レポート | `data/`（CSV/SQLite/`.md`レポート）、`*.pdf`、`*.3dm` | **しない** |
| 認証情報 | `credentials.json`、`token.json` | **しない** |
| 公開参考単価 | `public_reference_data/`（匿名化・集約・10円切り上げ） | する |
| 例示サンプル | `samples/` | する |

`.gitignore` で `data/`、`*.pdf`、`credentials.json`、`token.json` 等を除外している。

## 公開用参考単価の作り方

実データ由来の range master から、匿名化・集約・丸めを行う:

```bash
python -m steel_estimator.cli build-public-reference-prices \
  --plate-range-master ./data/plate_price_range_master.csv \
  --shape-range-master ./data/steel_shape_price_range_master.csv \
  --out-dir ./public_reference_data --rounding 10
```

出力:
- `public_plate_reference_prices.csv`（板厚別・集約）
- `public_shape_reference_prices.csv`（種別・寸法別・集約）
- `public_reference_price_notes.md`

### 削除する情報（個別明細に戻せる情報）

`vendor_name` / `quote_date` / `latest_quote_date` / `source_pdf` / `source_page` /
`spec_key`（exact）/ raw `unit_price` / `amount` / `quantity`。

### 集約・帯化

- `sample_count` は正確な数字でなく帯（`1` / `2-5` / `6-20` / `21+`）。
- `confidence` も帯（`low` / `medium` / `high`）。
- 板材は (材質×板厚) に集約し、最も信頼できる plate_class を代表に採る。
- 鋼材は (種別×材質×寸法) に集約し、定尺（最長 stock_length）を代表に採る。

## 価格の丸め（10円単位・切り上げ）

`ceil_to_unit(value, unit=10)` で**切り上げ**（安全側）。計算順:

1. 税抜値を10円単位で切り上げ → `ex_rounded`
2. 税込値 = `ex_rounded × (1+税率)` を10円単位で切り上げ

例: 273.5→280、295.5→300、706.7→710、5021→5030。
SS400 t6 の参考kg単価: 税抜 **270円/kg** → 税込 **300円/kg**（切り上げ）。

## 公開安全性監査

```bash
python -m steel_estimator.cli audit-public-data --public-dir ./public_reference_data
```

検査内容:
- 禁止列（vendor_name / source_pdf / source_page / quote_date / amount / quantity /
  spec_key / raw unit_price 等）が**無い**こと。
- 取引先名・PDF名・見積日らしき**値**が無いこと。
- `.gitignore` が `data/`・`credentials.json`・`token.json`・`*.pdf` を除外していること。
- （gitリポジトリの場合）`data/` の実データや認証情報が追跡されていないこと。

## 公開可否の判断基準

- 実データ・PDF・DB・取引先名・見積日・個別明細が含まれない。
- 公開用価格が10円単位切り上げ済み。
- README に「参考値であり実取引価格ではない」と明記。
- `run-demo` が公開用データだけで動く。

これらを満たせば公開リポジトリに入れて差し支えない。
