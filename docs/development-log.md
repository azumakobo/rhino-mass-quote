# 開発ログ

このドキュメントは、steel-estimator の開発経緯と設計変更の履歴を記録する。

---

## Phase 0: PDFからのデータ抽出（2025年末〜2026年初）

大量の鋼材見積PDF（231ファイル、約2728レコード）を機械解析し、過去の単価データを構造化することから始まった。

目的は「自社の過去見積PDFから価格相場を取り出し、次の見積に再利用する」ことだった。

- `pdfplumber` による PDF テキスト抽出
- 材料名・寸法・単価・重量のパース
- `steel_quotes.sqlite` への集積
- 品種・板厚ごとの価格レンジマスター生成

この段階では、元PDFの存在と変換の品質が課題だった。PDFの形式が一定でなく、パースに例外処理が多かった。

---

## Phase 1–3: CLI・見積エンジン構築

抽出した価格データを使って、重量→金額の変換を行う CLI を構築した。

- `ingest` / `export-review` / `estimate` コマンド
- レイヤー別数量から材料費を概算する `layer_estimate`
- `build-candidate-prices` / `analyze-candidate-prices`
- `build-price-range-masters`（板厚別・種別別中央値〜最大値）
- 消費税の内税/外税切り分け（`tax-handling.md` 参照）
- `unit_price` は税抜、税込は表示用に変換

---

## Phase R1〜R5: Rhino連携とWeb UI

Rhinoで作ったモデルから直接見積を出すことを目指し、Web UI と Rhino 連携を実装しようとした。

### R1: Rhino CSV エクスポート + CLI 見積

- `rhino_scripts/export_rhino_objects.py` でRhinoの全オブジェクトをCSVに書き出す
- CLI `estimate-public-rhino` でCSVを受け取り、公開参考単価で一括見積

### R2〜R4: mapping-ui・layer_mapping・CSV承認フロー

Rhinoのレイヤー名から材料カテゴリを推定し、単価を割り当てるフローを整備した。

- `mapping_ui.py`（FastAPI + HTML）でブラウザから単価・pricing_mode を編集・承認
- `layer_mapping.csv` に承認済みマッピングを保存し、次回見積で再利用
- `enrich-layer-mapping` / `build-public-reference-prices` / `audit-public-data`

このフローは機能していたが、**Rhinoで実作業中にブラウザを開いて単価を編集する操作が実務上不自然だった**。Rhinoのモデリング中断 → ブラウザ操作 → Rhino再開という切り替えが煩雑で、「見積を気軽に確認する」という目的に対して手順が多すぎた。

### R5: Rhino内パネル（`steel_estimate_rhino_panel.py`）

Rhinoのウィンドウ内にフローティングパネルを表示し、レイヤー別の重量・金額をリアルタイムで見る試みを実装した。

- `rhino_scripts/steel_estimate_rhino_panel.py`
- レイヤー名から自動マッピング → 体積→重量→kg単価→金額
- CSV出力ボタン

**課題**: パネルはRhinoのビュー操作の邪魔になりやすく、「開いたままモデリングする」には向いていなかった。また、パネルのウィジェット配置がRhinoのUI制約で限られており、単価カテゴリ選択・モード切替などの操作性が低かった。

---

## R6〜R6.3: 公開参考価格の精緻化

公開用に使えるデータとして、匿名化・集約・丸め済みの参考価格を整備した。

- `public_data.py` による匿名化パイプライン
- 取引先名・見積日・PDF名・個別明細の除去
- 10円単位切り上げ
- `public_reference_data/` への出力
- `audit-public-data` による混入チェック自動化
- `release-audit` による公開前監査一括実行

R6.2: `unit_price` は税抜に統一。  
R6.3: 価格レンジマスターの中央値〜最大値を公開参考として採用。  
RC1.1: 公開用匿名化データの最終整備と `run-demo` / `audit-public-data` の完備。

---

## 原点回帰: Mass と Quote への分離（2026-05-31）

開発を進めるにつれ、**実際のRhino作業でどう使うか**を再考した結果、以下の結論に至った。

**Rhinoで見積を確認したいシーンは2種類しかない:**

1. 「これは何kgくらいか？」— 素材と体積がわかれば計算できる。他のUIは不要。
2. 「これは大体いくらか？」— 重量にkg単価を掛けるだけ。カテゴリ選択だけあればよい。

Web UI・mapping-ui・CSV承認フロー・Rhino内パネルはどれも、この2つのシーンより複雑だった。

**そこで、原点回帰して2つのRhinoコマンドに分離した:**

### Mass（`mass_rhino.py` + `mass_core_for_rhino.py`）

- 選択した形状の体積から重量を計算する
- 素材密度を選ぶだけ（鉄・ステンレス・アルミ・木材・合板・MDF・アクリル・樹脂・カスタム）
- UserTextへの書き込みなし、CSV保存なし、確認ダイアログなし
- 軽く使えるv1の重量計算ツール

### Quote（`quote_estimate_rhino.py` + `steel_estimate_core_for_rhino.py`）

- 体積から重量を出し、公開参考単価の円/kgを掛けて概算材料費を出す
- 密度3択（鉄/ステンレス/アルミ）→ 単価カテゴリ選択 → 見積モード選択
- 通常見積（推奨）・安全側見積・手入力の3モード
- 安全係数1.2を通常/安全側に適用（手入力には適用しない）

**この分離により、どちらのツールも目的が明確になった。**

Webアプリとしての公開は取りやめ、Rhinoコマンドとして使える小さなツール集として公開する。

---

## 最終状態（2026-05-31）

| 項目 | 状態 |
|---|---|
| テスト | 306 passed |
| release-audit | PASS（全項目OK） |
| Mass | 完成（`mass_rhino.py` / `mass_core_for_rhino.py`） |
| Quote | 完成（`quote_estimate_rhino.py` / `steel_estimate_core_for_rhino.py`） |
| 公開参考価格 | 匿名化・10円切上げ済み |
| 実データ混入 | なし（.gitignoreで除外済み） |
| RhinoScripts同期 | 完了 |
