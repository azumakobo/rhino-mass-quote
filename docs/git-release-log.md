# git 公開前リリースログ

記録日: 2026-05-31  
状態: git 初期化前（`git init` 前）

---

## リポジトリ状態

このリポジトリは `git init` がまだ実行されていない（git 管理外のローカルディレクトリ）。  
初回コミット前の最終確認として、このログを記録する。

```
git status: リポジトリ未初期化
```

初回 push 手順（予定）:
```bash
git init
git add <公開対象ファイル>
git commit -m "feat: add Mass and Quote Rhino commands for steel estimation"
git remote add origin https://github.com/azumakobo/rhino-weight-calc.git
git push -u origin main
```

---

## テスト結果

```
pytest tests/ -q
306 passed in 0.54s
```

全306テストが PASSED。FAILED / ERROR なし。

---

## release-audit 結果

実行日: 2026-05-31

```
[OK] 実データ非混入(audit-public-data): OK
[OK] 公開参考価格CSV存在
[OK] 価格CSVに禁止列なし: OK
[OK] run-demo 完走: 税込合計¥44,037
[OK] estimate-public-rhino 完走（サンプル）: match 4 / 税込¥57,527
[OK] README存在: ./README.md
[OK] docs/data-security.md存在: ./docs/data-security.md
[OK] public_reference_data存在: ./public_reference_data
[OK] .gitignore保護: OK
[OK] 禁止ファイル非追跡(.pdf/.sqlite/.3dm等): OK
[OK] pytest: スキップ（--run-pytest で実行可）
=> 公開可能（PASS）
```

---

## 公開安全性確認

| 確認項目 | 結果 |
|---|---|
| 実見積PDF | .gitignore で除外済み |
| 実SQLiteデータベース | .gitignore で除外済み |
| 取引先名を含むCSV | data/ ごと .gitignore で除外済み |
| credentials.json | .gitignore で除外済み |
| token.json | .gitignore で除外済み |
| akiyama_quotes/ | .gitignore で除外済み |
| 公開参考価格CSVの禁止列 | audit-public-data PASS |
| Rhino 3dm ファイル | .gitignore で除外済み |

---

## 主要完成内容

### Mass（`mass_rhino.py` / `mass_core_for_rhino.py`）

- バージョン: `mass-2026-05-31`
- 対象素材: 鉄 / ステンレス / アルミ / 木材 / 合板 / MDF / アクリル / 樹脂 / カスタム（9種）
- 入力: Rhinoオブジェクト選択 → 素材選択 → （任意）kg単価入力
- 出力: 体積・重量・材料費をコマンドラインに表示
- 保存: 前回値を `~/Documents/RhinoScripts/mass_settings.json` に記録
- UserText書き込み・CSV保存・確認ダイアログ: なし
- 特徴: 軽いv1重量計算ツール。金属以外（木材・樹脂等）も扱う

### Quote（`quote_estimate_rhino.py` / `steel_estimate_core_for_rhino.py`）

- バージョン: `quote-debug-2026-05-31`
- Core バージョン: `steel-estimate-core-quote-factor-2026-05-31`
- 対象素材（密度用）: 鉄 / ステンレス / アルミ（3択）
- 概算用単価カテゴリ: 板t6〜t16 / 角パイプ / 丸パイプ / FB / 丸棒等
- 見積モード: 通常見積（推奨）/ 安全側見積 / 手入力
- 安全係数: `QUOTE_PRICE_FACTOR = 1.2`（推奨・安全側に適用、手入力には不適用）
- 安全側保守値: 中央値の 1.3〜2.0 倍に clamp
- 価格ソース: `public_reference_data/`（匿名化・10円単位切上げ済み参考価格）
- UserText: `quote_*` としてオブジェクトに書き込み
- 設定: `~/Documents/RhinoScripts/quote_settings.json`

---

## Web UI からRhinoコマンドへの方針転換

当初は以下を実装・検討した:

- FastAPI + HTML によるブラウザ mapping-ui
- レイヤー別 layer_mapping CSV の承認フロー
- Rhino内フローティングパネル（`steel_estimate_rhino_panel.py`）
- Rhino → CSV エクスポート → CLI 見積パイプライン

**転換理由:**

1. Rhinoのモデリング作業中にブラウザを開いて単価を編集する操作が不自然だった
2. Rhino内パネルはビュー操作の邪魔になりやすく、実務で開きっぱなしにしにくかった
3. CSV エクスポート → CLI → 結果確認という手順は、「重量を確認したい」という単純なニーズに対して手順が多すぎた
4. 「重量を知りたい」と「金額を出したい」という2つのシーンだけ対応すればよいと分かった

結果として、**Mass と Quote の2コマンドに分離**し、Rhinoのコマンドバーから起動するだけで完結するツールにした。

---

## RhinoScripts 同期状態（2026-05-31）

| ファイル | プロジェクト側 | RhinoScripts側 |
|---|---|---|
| mass_rhino.py | 存在 | 存在 |
| mass_core_for_rhino.py | 存在 | 存在 |
| quote_estimate_rhino.py | 存在 | 存在 |
| steel_estimate_core_for_rhino.py | 存在 | 存在 |

---

## まだ残る課題

1. **Quote の単価カテゴリ検索性**: カテゴリ数が多くなると ListBox でスクロールが必要。フィルタや検索機能が欲しい。
2. **公開参考価格の更新機能**: 市況変動時に単価テーブルを更新する仕組みが未整備。現在は手動で `build-public-reference-prices` を再実行する必要がある。
3. **板材の面積計算モード**: Quote は現在ポリサーフェス体積前提。板は面積×板厚 で体積を出せるが、実際のカット形状（型切）では面積計算の方が直感的なことがある。
4. **Rhinoボタン化**: ツールバーにボタンを追加するとより使いやすい。現在はAliasのみ。

---

## 今後の候補

| 項目 | 優先度 | 概要 |
|---|---|---|
| Quoteの価格カテゴリ検索性改善 | 中 | 材種でフィルタしてからカテゴリを選ぶ2段階UI |
| 公開単価テーブルの更新フロー整備 | 低 | `build-public-reference-prices` の自動化・通知 |
| Rhinoツールバーボタン化 | 低 | Alias に加えてツールバーアイコンを提供 |
| インストーラー化 | 低 | RhinoScripts へのコピーを自動化するスクリプト |
| Mass の UserText オプション | 低 | 「保存する」オプションを追加（標準はオフ） |

---

## コミットメッセージ案（初回）

```
feat: add Mass and Quote Rhino commands for steel weight and cost estimation

- Mass: lightweight Rhino command for material weight calculation
  supports steel, stainless, aluminum, wood, plywood, MDF, acrylic, resin, custom
- Quote: Rhino command for rough metal cost estimation
  uses anonymized public reference prices (not actual transaction prices)
  density (3 materials) and price category are selected separately
  QUOTE_PRICE_FACTOR=1.2 applied to recommended/conservative modes
- public_reference_data: anonymized, aggregated, rounded to 10 JPY
- release-audit: PASS, 306 tests passed
- docs: development-log, final-architecture, security, usage, checklist
```
