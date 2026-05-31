# Rhino コマンド使用ガイド（Mass / Quote）

## 概要

このリポジトリには2つのRhinoコマンドがある。

| コマンド | スクリプト | 用途 |
|---|---|---|
| `Mass` | `mass_rhino.py` | 素材密度から重量を計算する（金属・木材・樹脂等） |
| `Quote` | `quote_estimate_rhino.py` | 体積→重量→公開参考単価で概算見積を出す（金属3択） |

**重量だけ知りたい → Mass / 概算材料費を出したい → Quote**

---

## 事前準備: RhinoScripts への配置

Rhinoが実行するのは `~/Documents/RhinoScripts/` に置いたファイル。  
プロジェクト側（`rhino_scripts/`）を編集したら、同ディレクトリへコピーして同期する。

```bash
# プロジェクト側 → RhinoScripts へ同期（4ファイル）
cp rhino_scripts/mass_rhino.py              ~/Documents/RhinoScripts/
cp rhino_scripts/mass_core_for_rhino.py     ~/Documents/RhinoScripts/
cp rhino_scripts/quote_estimate_rhino.py    ~/Documents/RhinoScripts/
cp rhino_scripts/steel_estimate_core_for_rhino.py  ~/Documents/RhinoScripts/
```

> **注意:** Rhinoを起動したままコピーすると古いキャッシュが残ることがある。  
> 重要な更新後はRhinoを再起動するか、スクリプト起動時のバージョン出力で確認する。

---

## Alias 登録方法

**Rhinoceros > Preferences > Aliases** を開き、以下を追加する。

| Alias名 | コマンドマクロ |
|---|---|
| `Mass` | `! _-RunPythonScript "/Users/azumakobo/Documents/RhinoScripts/mass_rhino.py"` |
| `Quote` | `! _-RunPythonScript "/Users/azumakobo/Documents/RhinoScripts/quote_estimate_rhino.py"` |

> パスは環境に応じて変更すること。スペースが含まれる場合はダブルクォートで囲む。

登録後は、Rhinoのコマンドバーに `Mass` または `Quote` と入力するだけで起動できる。

---

## Mass の手順

1. Rhinoで重量を知りたいオブジェクト（ポリサーフェス等）を選択
2. コマンドバーに `Mass` と入力して実行
3. 素材をリストから選択（鉄 / ステンレス / アルミ / 木材 / 合板 / MDF / アクリル / 樹脂 / カスタム）
4. 必要であれば kg単価を入力（省略可）
5. コマンドラインに体積・重量・材料費が表示される

**保存確認・UserTextへの書き込みは出ない。**  
前回選択した素材は `~/Documents/RhinoScripts/mass_settings.json` に記録される。

---

## Quote の手順

1. Rhinoで見積対象の金属オブジェクトを選択
2. コマンドバーに `Quote` と入力して実行
3. 起動ログでバージョンとファイルパスを確認（取り違え防止）
4. **重量計算用素材を選択**（3択: 鉄 / ステンレス / アルミ）
5. **概算用単価カテゴリを選択**（板 t6 / 板 t9 / 角パイプ / 丸パイプ / FB等）
   - 選択時に recommended（通常）と conservative（安全側）の参考円/kgが表示される
6. **見積モードを選択**:
   - 通常見積（推奨）: 公開参考単価 × 安全係数 1.2
   - 安全側見積: 保守値 × 安全係数 1.2
   - 手入力: ユーザー入力値をそのまま使用（安全係数なし）
7. 手入力モードの場合は円/kg を入力
8. 結果がコマンドライン・ダイアログに表示され、UserTextに書き込まれる

設定は `~/Documents/RhinoScripts/quote_settings.json` に記録される。

---

## Mass と Quote の違い

| 項目 | Mass | Quote |
|---|---|---|
| 素材選択 | 9種類（金属・木材・樹脂・カスタム） | 3択（鉄・ステンレス・アルミ） |
| 価格データ | なし（任意でkg単価手入力） | 公開参考価格CSVを自動参照 |
| 単価カテゴリ | なし | あり（板厚・パイプ種別等） |
| 見積モード | なし | 通常 / 安全側 / 手入力 |
| UserText書き込み | なし | あり（`quote_*`） |
| 用途 | 重量確認 | 概算見積 |

---

## よくあるエラーと対処

### 1. 古い core を読んでいる（バージョン不一致）

**症状:** Quote 起動時に `CORE_VERSION: steel-estimate-core-quote-factor-2026-05-31` 以外が出る、または `AttributeError: QUOTE_PRICE_FACTOR` が出る。

**原因:** Rhinoセッションで古いモジュールがキャッシュされている。  
**対処:** Rhinoを再起動する。または Quote スクリプトが `sys.modules.pop` でキャッシュクリアしているか確認する。

---

### 2. `QUOTE_PRICE_FACTOR` がない

**症状:** `AttributeError: module 'steel_estimate_core_for_rhino' has no attribute 'QUOTE_PRICE_FACTOR'`  
**原因:** RhinoScripts 側の `steel_estimate_core_for_rhino.py` が古いバージョン。  
**対処:** プロジェクト側から再コピーしてRhinoを再起動する。

```bash
cp rhino_scripts/steel_estimate_core_for_rhino.py ~/Documents/RhinoScripts/
```

---

### 3. 体積が取れない

**症状:** 「体積が取得できませんでした」「volume = 0」のようなメッセージが出る。  
**原因:** オブジェクトが閉じたソリッドでない（開いたサーフェス・メッシュ・カーブ等）。  
**対処:** Rhinoで `_Check` や `_ShowEdges` で形状の閉じ具合を確認する。  
閉じたポリサーフェスにしてから再実行する。

---

### 4. Alias のパスが違う

**症状:** `Mass` / `Quote` を実行すると「ファイルが見つかりません」エラーが出る。  
**原因:** Preferences > Aliases のパスが実際のファイル場所と一致していない。  
**対処:** `ls ~/Documents/RhinoScripts/mass_rhino.py` でファイルの存在を確認し、  
Aliases のパスを実際のパスに合わせる。

---

### 5. RhinoScripts 側とプロジェクト側が同期されていない

**症状:** バージョンが古い、最新の修正が反映されていない。  
**確認方法:** 起動ログの `version:` と `path:` を見る。  

```
----- Quote script -----
path: /Users/azumakobo/Documents/RhinoScripts/quote_estimate_rhino.py
version: quote-debug-2026-05-31
```

プロジェクト側と RhinoScripts 側の両方で `grep "QUOTE_VERSION\|MASS_VERSION"` してバージョンが一致しているか確認する。

---

## 参考価格の読み方

Quote 起動時に表示される参考円/kgの意味:

- **通常見積（推奨）**: 中央値 × 1.2（安全係数込み）
- **安全側見積**: 保守値 × 1.2（安全係数込み）

これらは **実取引価格ではなく**、制作初期の概算用参考価格（匿名化・丸め済み）。  
正式発注前には必ず実見積を取ること。
