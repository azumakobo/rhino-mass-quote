# GitHub 公開前チェックリスト

GitHub に push する前に、以下をすべて確認する。

---

## 1. 実データ非混入チェック

- [ ] `data/` ディレクトリが git 管理外であること（`.gitignore` で除外済み）
- [ ] `*.pdf` が管理外であること
- [ ] `*.sqlite` / `*.db` が管理外であること
- [ ] `*.3dm`（Rhino モデル）が管理外であること
- [ ] `credentials.json` が管理外であること
- [ ] `token.json` が管理外であること
- [ ] `quotes/` / `akiyama_quotes/` が管理外であること
- [ ] `release_audit_report.md` が管理外であること（`.gitignore` 済み）
- [ ] `demo_output/` / `public_demo_output/` が管理外であること

確認コマンド:
```bash
git ls-files | grep -E '\.(pdf|sqlite|db|3dm)$'   # 何も出ないこと
git ls-files | grep -E 'credentials|token\.json'   # 何も出ないこと
```

---

## 2. 公開参考価格チェック

- [ ] `public_reference_data/public_plate_reference_prices.csv` が存在する
- [ ] `public_reference_data/public_shape_reference_prices.csv` が存在する
- [ ] `public_reference_data/public_reference_price_notes.md` が存在する
- [ ] 価格CSVに禁止列（supplier / quote_date / pdf_file / detail_id）が含まれていない
- [ ] `audit-public-data` が PASS している

```bash
python -m steel_estimator.cli audit-public-data --public-dir ./public_reference_data
```

---

## 3. release-audit PASS

```bash
python -m steel_estimator.cli release-audit
```

- [ ] 実データ非混入(audit-public-data): OK
- [ ] 公開参考価格CSV存在: OK
- [ ] 価格CSVに禁止列なし: OK
- [ ] run-demo 完走: OK
- [ ] estimate-public-rhino 完走（サンプル）: OK
- [ ] README存在: OK
- [ ] docs/data-security.md存在: OK
- [ ] public_reference_data存在: OK
- [ ] .gitignore保護: OK
- [ ] 禁止ファイル非追跡: OK
- [ ] **総合判定: PASS**

---

## 4. テスト全通過

```bash
python -m pytest tests/ -q
```

- [ ] 全テスト PASSED（現在 306 passed）
- [ ] FAILED / ERROR が 0 件

---

## 5. README の内容確認

- [ ] 「このリポジトリには Mass と Quote の2つの完成品がある」と書いてある
- [ ] Mass の用途（重量計算）が書いてある
- [ ] Quote の用途（金属概算見積）が書いてある
- [ ] Rhinoコマンドとして使う方針が書いてある
- [ ] Webアプリ化をやめた理由が書いてある（または development-log へのリンク）
- [ ] Alias 登録方法（Preferences > Aliases）が書いてある
- [ ] 「公開参考価格は実取引価格ではない」と書いてある
- [ ] 「正式見積には使えない」と書いてある
- [ ] `public_reference_data` が匿名化・丸め済みであると書いてある

---

## 6. docs の確認

- [ ] `docs/development-log.md` — 開発経緯（Web UI → 原点回帰）
- [ ] `docs/final-architecture.md` — Mass / Quote の最終仕様
- [ ] `docs/security-and-public-data.md` — 公開参考価格の扱い・免責
- [ ] `docs/rhino-command-usage.md` — Alias登録・手順・よくあるエラー
- [ ] `docs/release-checklist.md` — このファイル
- [ ] `docs/git-release-log.md` — 最終コミット前記録

---

## 7. RhinoScripts 同期確認

- [ ] `~/Documents/RhinoScripts/mass_rhino.py` がプロジェクト側と同じバージョン
- [ ] `~/Documents/RhinoScripts/mass_core_for_rhino.py` が同期済み
- [ ] `~/Documents/RhinoScripts/quote_estimate_rhino.py` が同期済み
- [ ] `~/Documents/RhinoScripts/steel_estimate_core_for_rhino.py` が同期済み

バージョン確認:
```bash
grep "MASS_VERSION\|QUOTE_VERSION\|CORE_VERSION" \
  rhino_scripts/mass_rhino.py \
  rhino_scripts/quote_estimate_rhino.py \
  rhino_scripts/steel_estimate_core_for_rhino.py

grep "MASS_VERSION\|QUOTE_VERSION\|CORE_VERSION" \
  ~/Documents/RhinoScripts/mass_rhino.py \
  ~/Documents/RhinoScripts/quote_estimate_rhino.py \
  ~/Documents/RhinoScripts/steel_estimate_core_for_rhino.py
```

---

## 8. Quote 動作確認

- [ ] `Quote` 起動時にバージョン・パスが表示される
- [ ] `QUOTE_PRICE_FACTOR: 1.2` が起動ログに出る
- [ ] `CORE_VERSION: steel-estimate-core-quote-factor-2026-05-31` が出る
- [ ] 体積が取れるポリサーフェスで概算金額が表示される

---

## 9. git 状態確認

```bash
git status
git diff --stat
git ls-files | sort
```

- [ ] コミット対象に実データ・クレデンシャルが混入していない
- [ ] `public_reference_data/` のみが価格データとして管理される
- [ ] `.venv/` / `__pycache__/` / `.DS_Store` が管理外

---

すべて確認したら、`git add` → `git commit` → `git push` に進む。
