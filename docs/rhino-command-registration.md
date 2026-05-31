# Rhino コマンド登録（Quote / Mass）

ScriptEditorで毎回スクリプトを開かず、Rhinoのコマンド欄に `Quote` / `Mass` と打つだけで
起動できるよう、**エイリアス（Alias）**を登録します。

## 実行ファイル（Rhinoが実際に読む場所）

| コマンド | 実行ファイル |
|---|---|
| Quote（概算見積） | `/Users/azumakobo/Documents/RhinoScripts/quote_estimate_rhino.py` |
| Mass（重量計算） | `/Users/azumakobo/Documents/RhinoScripts/mass_rhino.py` |

依存ファイル（同じ `RhinoScripts/` に配置済み・コピー不要）:
- `steel_estimate_core_for_rhino.py`（Quote用）
- `mass_core_for_rhino.py`（Mass用）

公開参考価格は Quote が自動参照します（プロジェクト側のまま）:
`/Users/azumakobo/Documents/claude/projects/steel-estimator/public_reference_data/`

> プロジェクト側の原本 `…/steel-estimator/rhino_scripts/` を編集したら、`RhinoScripts/` に
> コピーし直してください（下記「更新手順」）。実行ファイルの取り違え防止に、起動時ログ冒頭へ
> `path:` と `version:`（`quote-2026-05-31` / `mass-2026-05-31`）を表示します。

## コマンドマクロ（Command macro）

Quote:
```
! _-RunPythonScript "/Users/azumakobo/Documents/RhinoScripts/quote_estimate_rhino.py"
```

Mass:
```
! _-RunPythonScript "/Users/azumakobo/Documents/RhinoScripts/mass_rhino.py"
```

## エイリアス登録手順（Rhino 8 Mac）

1. メニュー **Rhinoceros > Preferences（環境設定）** を開く。
2. 左の一覧から **Aliases（エイリアス）** を選ぶ。
3. **＋（新規）** で行を追加し、次を入力する。

   | Alias（別名） | Command macro（コマンドマクロ） |
   |---|---|
   | `Quote` | `! _-RunPythonScript "/Users/azumakobo/Documents/RhinoScripts/quote_estimate_rhino.py"` |
   | `Mass`  | `! _-RunPythonScript "/Users/azumakobo/Documents/RhinoScripts/mass_rhino.py"` |

4. ダイアログを閉じる。
5. Rhinoのコマンド欄に **`Quote`** と打つ → 概算見積が起動。
   **`Mass`** と打つ → 重量計算が起動。

> `Mass` がRhino標準コマンドと競合する場合は、別名（例 `Q` / `Wt` / `MassEst`）を使ってください。

## Quote と Mass の役割

### Quote（金属の概算見積）
- 重量計算用素材は **鉄（SS400/STK/STKR）/ ステンレス（SUS304）/ アルミ（A5052）の3択**。
- 次画面で**細かい価格カテゴリ**（板t6/t9、角パイプ、丸パイプ、FB…）を選ぶ。
- 公開用参考価格CSVの円/kgを使用（実取引価格ではない）。見積方法: 通常見積（中央値）/安全側見積（最大値）/手入力。

### Mass（重量計算）
- 木材・合板・MDF・アクリル・樹脂・カスタムを含む素材から密度を選び重量を出す。
- **余計なUserText書き込み確認・CSV保存確認は出さない**（軽い重量計算）。

## 更新手順（原本を直したら反映）

```bash
SRC=/Users/azumakobo/Documents/claude/projects/steel-estimator/rhino_scripts
DST=/Users/azumakobo/Documents/RhinoScripts
cp "$SRC/quote_estimate_rhino.py"        "$DST/"
cp "$SRC/mass_rhino.py"                  "$DST/"
cp "$SRC/steel_estimate_core_for_rhino.py" "$DST/"
cp "$SRC/mass_core_for_rhino.py"         "$DST/"
```

## 実機確認

### A. Quote
1. 適当な Box を作成して選択。
2. コマンド欄に `Quote`。
3. ログ冒頭に `version: quote-2026-05-31` が出るのを確認。
4. 重量計算用素材（3択）→ 概算用単価カテゴリ → 見積方法 を選ぶ。
5. 概算見積（重量・kg単価・概算材料費）が表示される。

### B. Mass
1. 同じ Box を選択。
2. コマンド欄に `Mass`。
3. ログ冒頭に `version: mass-2026-05-31` が出るのを確認。
4. 素材を選ぶ → 重量が表示される。
5. **UserText確認・CSV保存確認が出ない**ことを確認。

## エンコーディング / Python互換（RunPythonScript対策）

`_-RunPythonScript` が（ScriptEditorのCPython3でなく）従来のIronPython 2系で読むと、
日本語コメントで `Non-ASCII character ... no encoding declared` エラーになります。対策として：

- 入口スクリプト（quote/mass）の**1行目に `#! python 3`**（Rhino 8 が CPython3 で実行）、
  **2行目に `# -*- coding: utf-8 -*-`**（エンコーディング宣言）を入れています。
- 依存core（steel_estimate_core / mass_core）の**1行目に `# -*- coding: utf-8 -*-`**。
- Python3専用の**アンダースコア数値（`1_000_000`）を排除**、ファイル入出力は **`io.open(...)`**
  （Python2/3共通でencoding対応）に統一。
- f-string・型注釈・walrus等のPython3専用構文は不使用。

これにより、CPython3で実行されれば確実に動き、万一IronPythonで読まれても1行目の
エンコーディングエラーは出ません（その場合でも `#! python 3` によりCPython3へ切り替わる想定）。

> それでも `RunPythonScript` がCPython3に切り替わらずエラーが続く場合は、ScriptEditorで
> 一度該当スクリプトを開いて言語が **Python 3 (CPython / RhinoCommon)** になっているか確認するか、
> エラー全文を共有してください（薄いASCII名ラッパーへの切替も可能）。

## 備考: もう一つの重量計算 `weight_calc.py`
`RhinoScripts/weight_calc.py` は従来からの重量計算ツール（Block展開・真鍮/銅/コンクリート等を含む
リッチ版・mass-lite-2026-05-31で確認ダイアログ除去済）。`Mass` をこちらに割り当てたい場合は、
マクロのパスを `…/weight_calc.py` に変えてください（素材構成が異なります）。
