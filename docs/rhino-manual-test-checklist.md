# Rhino 8 実機テスト チェックリスト（最短手順）

Rhino 8 (Mac) でデモモデル作成 → CSV出力 → 公開参考単価だけで見積、までを手動で確認する。
**手動Runが正式フロー**（ScriptEditorへの自動貼り付け・自動Runは環境差が大きいため行わない）。
公開用参考価格は概算用で、**実取引価格ではない**。

## 事前準備（ターミナル）

```bash
cd <repo>
python -m venv .venv && source .venv/bin/activate
pip install -e ".[ui]"
bash scripts/open_rhino_export_helper.sh         # export のパスをコピー
bash scripts/open_rhino_export_helper.sh --demo  # create_demo のパスをコピー
```

## チェックリスト

- [ ] **1. Rhino 8 を起動**（新規ドキュメント推奨。既存モデルは消さない設計）
- [ ] **2. モデル単位が mm**（`_Units` で確認。mm以外でも動くが notes に換算記録）
- [ ] **3. `_ScriptEditor` を開く**
- [ ] **4. 言語が「Python 3 (CPython / RhinoCommon)」**（IronPython/Python2では動かない）
- [ ] **5. `create_demo_rhino_model.py` を Open → Run**
- [ ] **6. デモレイヤーと形状ができたか**（Layersパネルに次の7つ）
      - `PL_SS400_t6`（1000×500の閉矩形・面積）
      - `SQPIPE_STKR_40x40_t2.3`（**中空ポリサーフェス**・体積）
      - `PIPE_STK_D48.6_t2.3`（**中空ポリサーフェス**・体積）
      - `FB_SS400_50x4.5`（**ソリッド**・体積）
      - `ANGLE_SS400_40x40_t3`（**L形ソリッド**・体積）
      - `BOLT_TEST`（点6個）
      - `IGNORE_GUIDE`（補助線）
      > 標準は**ポリサーフェス体積方式**。鋼材は閉じた押し出しで作る（中心線カーブは旧仕様）。
- [ ] **7. `export_rhino_objects.py` を Open → Run**
- [ ] **8. 保存ダイアログで `./data/rhino_objects.csv` を選ぶ**（未保存ならDesktopに自動出力）
- [ ] **9. CLIで検証**
      `python -m steel_estimator.cli validate-rhino-csv --input ./data/rhino_objects.csv`
- [ ] **10. 公開参考単価だけで見積**
      `python -m steel_estimator.cli estimate-public-rhino --rhino-csv ./data/rhino_objects.csv --out-dir ./public_demo_output --tax-rate 0.10`
- [ ] **11. `what_costs_how_much.csv` と `public_rhino_estimate_report.md` を確認**
      （5材料レイヤーがmatch、税抜/税込・recommended/conservative）
- [ ] **12.（任意）期待CSVと差分確認**
      `python -m steel_estimator.cli compare-rhino-csv --actual ./data/rhino_objects.csv --out ./data/rhino_csv_compare_report.md`
- [ ] **13.（任意）UIで単価調整**
      `python -m steel_estimator.cli mapping-ui --out-dir ./public_demo_output --public-reference ./public_reference_data`

## 失敗時の確認項目

| 症状 | 確認 |
|---|---|
| `RhinoCommon専用です` と出る | ScriptEditorの言語が **Python 3 (CPython / RhinoCommon)** か |
| レイヤーが作られない | 5でエラーが出ていないか。ScriptEditor下部のログを見る |
| 面積が 0（板材） | 板が**閉じた平面曲線/サーフェス**になっているか |
| 体積が 0（鋼材） | 鋼材が**閉じたポリサーフェス**か（`_Volume`で確認・`_Cap`/`_Join`で閉じる） |
| 重量が過大（角/丸パイプ） | 中空ではなく**ソリッド棒**になっていないか（内側profileで穴を開ける） |
| ANGLEがneeds_review | 公開参考にangleのkg単価が無いため（JIS重量要）。UIで kg単価を手入力 |
| 寸法が想定の1/1000等 | **モデル単位がmmか**（m単位だと値が異なる→notesに換算記録） |
| CSVが文字化け | UTF-8 with BOM で出力される。Excelはそのまま開ける |
| 保存先に日本語/空白 | パスに日本語・空白があっても動く（ダイアログ/Desktopフォールバック） |
| validate で必須ヘッダー欠落 | 古いexportを使っていないか。最新の export_rhino_objects.py を使う |
| match 0件 | レイヤー名が `<種別>_<材質>_<寸法>` 規約か。寸法が参考価格に存在するか |

結果は `docs/rhino-manual-test-result-template.md` をコピーして記録する。
