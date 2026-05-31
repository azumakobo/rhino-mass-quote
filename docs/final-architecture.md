# 最終アーキテクチャ

このリポジトリの完成形は **Mass** と **Quote** の2つのRhinoコマンドである。

---

## 共通方針

- **Rhinoの `_Volume` / `VolumeMassProperties` で取得できる体積を正とする。**
- 重量の計算は `weight_kg = volume_mm3 × density_g_cm3 × 1e-6` のみ。
- ツール側で形状の断面を再解釈したり、レイヤー名から寸法を逆算したりはしない。
- **正確な重量が必要なら、Rhino側で正しい体積の形状を作る。**  
  中空パイプは内側プロファイルで穴を開けた閉ソリッドにする。板は閉平面か閉ソリッド。
- 体積 × 密度 × kg単価という単純な流れで概算を出す。複雑な形状解釈は行わない。

---

## Mass

### 目的

Rhinoで選択した形状の **重量を計算する**。金属以外の素材も扱う。

### 入力

1. Rhino上で対象オブジェクト（ポリサーフェス・ブレップ・サーフェスなど）を選択
2. 素材を選択（リスト）
3. 必要であれば kg単価を入力（任意）

### 処理

```
volume_mm3 ← Rhino VolumeMassProperties（単位系に応じてmm換算）
weight_kg  = volume_mm3 × density_g_cm3 × 1e-6
cost       = weight_kg × unit_price_per_kg（任意入力時のみ）
```

### 出力

Rhinoのコマンドライン（および ScriptEditor 出力欄）に表示:
- 体積（mm³ / cm³ / m³）
- 重量（kg）
- 材料費（kg単価を入力した場合のみ）

### 対象素材

| 内部キー | 表示名 | 密度（g/cm³） |
|---|---|---|
| steel | 鉄 | 7.85 |
| stainless | ステンレス | 7.93 |
| aluminum | アルミ | 2.70 |
| wood | 木材 | 0.50 |
| plywood | 合板 | 0.55 |
| mdf | MDF | 0.75 |
| acrylic | アクリル | 1.19 |
| resin | 樹脂 | 1.20 |
| custom | カスタム | 手入力 |

### 設定ファイル

`~/Documents/RhinoScripts/mass_settings.json`

前回選択した素材・kg単価を記録する。UserTextへの書き込み・CSV保存・確認ダイアログは行わない。

### UserText・CSVを標準では使わない理由

「重量だけ知りたい」シーンで、毎回「保存しますか？」と確認を出すのは煩雑。  
Massは軽いv1ツールとして、表示して終わるだけにする。  
保存が必要なら、表示された数値をユーザーが手動でメモする。

---

## Quote

### 目的

Rhinoで選択した形状から **概算材料費（金属）を出す**。  
公開用参考価格データの円/kgを使って概算見積を行う。

### 入力

1. Rhino上で対象オブジェクト（金属材）を選択
2. 重量計算用素材を選択（3択）
3. 概算用単価カテゴリを選択（板厚・パイプ種別など）
4. 見積モードを選択（通常見積 / 安全側見積 / 手入力）
5. 手入力モード時は円/kgを手入力

### 重量計算用素材（密度選択・3択）

| 内部キー | 表示名 | 密度（g/cm³） |
|---|---|---|
| steel | 鉄（SS400 / STK / STKR） | 7.85 |
| stainless | ステンレス（SUS304） | 7.93 |
| aluminum | アルミ（A5052） | 2.70 |

**重量計算用素材（密度）と概算用単価カテゴリ（円/kg）は分離している。**  
例：「アルミ板として体積から重量を出し、ステンレス板の単価を参照する」ことはしない。  
素材を選んだ後、その素材に対応した単価カテゴリから選ぶ。

### 概算用単価カテゴリ

`public_reference_data/public_shape_reference_prices.csv`（形鋼・パイプ・FB等）および  
`public_reference_data/public_plate_reference_prices.csv`（板材・板厚別）から読み込む。

カテゴリ例：
- 板 t6, 板 t9, 板 t12, 板 t16（板厚別）
- 角パイプ（小・中・大）
- 丸パイプ
- フラットバー (FB)
- 丸棒
- アングル等

### 見積モードと安全係数

| モード | 内部値 | 説明 |
|---|---|---|
| 通常見積（推奨） | `recommended` | 中央値 × 安全係数 |
| 安全側見積 | `conservative` | 保守値 × 安全係数 |
| 手入力 | `manual` | ユーザー入力値をそのまま使用（安全係数なし） |

**`QUOTE_PRICE_FACTOR = 1.2`（安全係数）を `recommended` と `conservative` に適用する。**  
`manual` には安全係数を適用しない。

`conservative` の元値は中央値の **1.3〜2.0倍にclamp** して外れ値を抑制している  
（詳細は `docs/security-and-public-data.md` 参照）。

### 処理フロー

```
volume_mm3    ← Rhino VolumeMassProperties
weight_kg     = volume_mm3 × density × 1e-6
unit_price    = public_price × QUOTE_PRICE_FACTOR     # recommended / conservative
             or manual_input                           # manual
cost_ex_tax   = weight_kg × unit_price
cost_inc_tax  = cost_ex_tax × (1 + tax_rate)
```

### 出力

Rhinoのコマンドラインおよびダイアログに表示:
- 体積・重量
- 選択した単価カテゴリ・円/kg
- 税抜概算金額
- 税込概算金額（消費税 10%）
- UserText `quote_*` として対象オブジェクトに書き込む

### 設定ファイル

`~/Documents/RhinoScripts/quote_settings.json`

前回選択した素材・カテゴリ・モード・手入力単価を記録する。

### public_reference_data の位置づけ

`public_reference_data/` に含まれる価格データは:
- 実見積PDFから集計・匿名化・10円単位切上げしたもの
- 取引先名・見積日・PDF名・個別明細は含まない
- **実取引価格ではなく、制作初期の概算用参考価格**
- 市況・ロット・地域・加工条件で変動するため、正式見積には使えない

詳細は `docs/security-and-public-data.md` 参照。

---

## ファイル構成（Rhinoコマンド関係）

```
rhino_scripts/
  mass_rhino.py                    ← Mass コマンド本体
  mass_core_for_rhino.py           ← Mass ロジック（Rhino非依存）
  quote_estimate_rhino.py          ← Quote コマンド本体
  steel_estimate_core_for_rhino.py ← Quote ロジック（Rhino非依存）
  weight_cost_estimate_rhino.py    ← 旧名の互換シム（Quote を呼ぶだけ）
  steel_estimate_rhino_panel.py    ← レイヤーパネル（補助ツール）
  export_rhino_objects.py          ← Rhino → CSV エクスポート（補助）
  create_demo_rhino_model.py       ← デモモデル生成（補助）

~/Documents/RhinoScripts/          ← Rhinoが実際に読む実行場所
  mass_rhino.py                    ← プロジェクトと同期
  mass_core_for_rhino.py           ← プロジェクトと同期
  quote_estimate_rhino.py          ← プロジェクトと同期
  steel_estimate_core_for_rhino.py ← プロジェクトと同期
```

プロジェクト側（`rhino_scripts/`）と RhinoScripts 側は手動で同期する。  
同期手順は `docs/rhino-command-usage.md` 参照。
