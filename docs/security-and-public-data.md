# 公開参考価格のセキュリティと安全性

## 元データと公開データの違い

| 項目 | 元データ（非公開） | 公開版（`public_reference_data/`） |
|---|---|---|
| ソース | 実見積PDF 231ファイル、約2728レコード | 上記から匿名化・集約・丸め済み |
| 取引先名 | あり | **削除済み** |
| 見積日 | あり | **削除済み** |
| PDF名 | あり（ファイル名に案件名を含む） | **削除済み** |
| 個別明細 | あり | **削除済み**（カテゴリ集計のみ） |
| 単価 | 実取引価格 | **10円単位切り上げ** |
| 格納場所 | `data/`（.gitignore で管理外） | `public_reference_data/`（管理対象） |

---

## 匿名化処理の手順

1. `build-public-reference-prices` コマンドで実DBから集計
2. カテゴリ（板厚・材種・形状）ごとに中央値・最大値を算出
3. **個別レコード・取引先情報・日付を除去**
4. 単価を **10円単位切り上げ**（`math.ceil(v / 10) * 10`）
5. `audit-public-data` で禁止列の非混入を確認
6. `public_reference_data/` に出力

`audit-public-data` が確認する禁止列:
- `supplier` / `company` / `vendor`（取引先名）
- `quote_date` / `date`（見積日）
- `pdf_file` / `filename`（PDFファイル名）
- `detail_id` / `line_id`（個別明細ID）

---

## 安全係数（`QUOTE_PRICE_FACTOR`）

Quote コマンドでは、公開参考価格に **安全係数 1.2 を乗じる**（`QUOTE_PRICE_FACTOR = 1.2`）。

理由: 公開参考価格は時期・ロット・加工条件によって変動する。  
「概算見積が実見積より安く出て発注失敗する」リスクを低減するため、高め方向に補正する。

```
実際に使われる単価 = 公開参考単価 × 1.2
```

**`manual`（手入力）モードには安全係数を適用しない。** ユーザーが入力した値をそのまま使う。

---

## 安全側見積（conservative）の clamp

`conservative`（安全側見積）の元値は、価格分布の保守的な推定値（高め側）を使う。  
ただし、統計的外れ値が conservative に入るのを防ぐため、**中央値の 1.3〜2.0 倍にclamp** している。

```
conservative_raw  ← 価格分布の上位推定値
conservative_used = clamp(conservative_raw, median × 1.3, median × 2.0)
```

これにより、数倍になった外れ値単価が conservative 経由で出力されることを防ぐ。

---

## 免責事項

- `public_reference_data/` の価格は **実取引価格ではない**。
- 価格は **市況・ロット・地域・加工条件・仕入れ先によって変動する**。
- 鉄鋼市況は年間で数十%変動することがある。古いデータは参考値として割引いて使うこと。
- 板材は外接矩形ベースの参考価格のため、形状によっては重量を過大評価しうる（kg単価は割安方向）。
- **正式発注前には必ず各業者へ見積を取り直すこと。**
- このツールの価格は研究・制作初期の概算・オーダー確認用であり、**見積書の代替にはならない**。

---

## release-audit による公開前チェック

```bash
python -m steel_estimator.cli release-audit
```

以下を自動確認する:
- `audit-public-data` 実行（禁止列混入チェック）
- 公開参考価格CSVの存在確認
- `run-demo` の完走確認
- `estimate-public-rhino` のサンプル実行
- README・docs/data-security.md の存在
- `.gitignore` による実データ保護の確認
- 禁止拡張子（`.pdf` / `.sqlite` / `.3dm`）の非追跡確認

**release-audit が PASS することを公開前に確認すること。**
