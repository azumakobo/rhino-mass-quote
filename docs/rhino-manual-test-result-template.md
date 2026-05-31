# Rhino 8 実機テスト結果（記録テンプレート）

このファイルをコピーして実行結果を記入する（実機で試した人が埋める）。
公開用参考価格は概算用で、実取引価格ではない。

---

## 実行環境

- 実行日: YYYY-MM-DD
- macOS version: （例 14.x / 15.x）
- Rhino version: （例 Rhino 8 SR x）
- Python mode: Python 3 (CPython / RhinoCommon) / その他（要記入）
- モデル単位: Millimeters / その他（　）

## 1. create_demo_rhino_model.py

- 結果: 成功 / 失敗
- 作成レイヤー数: （期待 7）
- 作成されたレイヤー: PL_SS400_t6 / SQPIPE_STKR_40x40_t2.3 / PIPE_STK_D48.6_t2.3 /
  FB_SS400_50x4.5 / ANGLE_SS400_40x40_t3 / BOLT_TEST / IGNORE_GUIDE
- メモ:

## 2. export_rhino_objects.py

- 結果: 成功 / 失敗
- 出力CSVパス: ./data/rhino_objects.csv （または Desktop）
- オブジェクト数 / レイヤー数:
- 面積取得件数 / 曲線長取得件数 / 体積取得件数:
- notesあり件数:
- モデル単位・scale_to_mm:
- メモ:

## 3. validate-rhino-csv

```
python -m steel_estimator.cli validate-rhino-csv --input ./data/rhino_objects.csv
```
- 結果: OK / NG
- error / warning:

## 4. estimate-public-rhino

```
python -m steel_estimator.cli estimate-public-rhino \
  --rhino-csv ./data/rhino_objects.csv --out-dir ./public_demo_output --tax-rate 0.10
```
- match件数: （期待 5）
- unmatched件数:
- needs_review件数:
- 税抜合計 / 消費税 / 税込合計: ¥　 / ¥　 / ¥　
- recommended税込 / conservative税込: ¥　 / ¥　

## 5. compare-rhino-csv（任意）

```
python -m steel_estimator.cli compare-rhino-csv --actual ./data/rhino_objects.csv \
  --out ./data/rhino_csv_compare_report.md
```
- 総合: 一致 / 差分あり
- 未出力レイヤー / 余分レイヤー:
- レイヤー名は想定通りか:
- 面積は取れているか:
- 曲線長は取れているか:
- object_type は想定通りか:
- notes にエラーは無いか:

## 6. 発生したエラーと修正

- エラー内容:
- 原因:
- 修正内容（Rhinoスクリプト側の最小修正など）:

## 7. 残課題

-

## 8. 判定

- Rhino 8 Mac で動作確認: できた / できていない
- （できた場合のみ）READMEに「Rhino 8 Macで動作確認済み」を追記してよい
