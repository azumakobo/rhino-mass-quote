# Rhino内 概算見積ウィンドウ ガイド（標準導線・Phase RC4）

最終更新: 2026-05-31

**今後の標準導線は Rhino内UI**です。Webブラウザ（mapping-ui）を開かず、Rhino上でレイヤー別金額と
合計を確認できます。RC4版は **表示専用＋CSV出力**（単価/pricing_mode編集は後続フェーズ）。

> 価格は `public_reference_data/` の公開用参考価格（匿名化・集約・10円切上げ済）。
> **実取引価格ではありません。実発注前に必ず実見積で確認**してください。

> **このツールは、レイヤー内の volume を材料量として扱い、レイヤー名から推定した
> 材料カテゴリ・kg単価を掛けます。** デモ形状は単純Boxで構いません（断面再現は不要）。
> 実案件では、ユーザーが作った Rhino形状の volume がそのまま見積根拠になります。
> 正確な材料量が必要な場合は、Rhino上で正しい体積の形状を作ってください。

## 使い方

1. Rhino 8 でモデルを開く（鋼材は**閉じたポリサーフェス**、板は閉平面曲線/サーフェス）。
2. `_ScriptEditor` を開き、言語を **Python 3 (CPython / RhinoCommon)** にする。
3. `rhino_scripts/steel_estimate_rhino_panel.py` を Open → **Run**。
4. 「Steel Estimator」ウィンドウが Rhino 内に開く。
5. レイヤー別の金額を確認。**再計算**でモデル変更を反映、**CSV出力**で保存。

## 画面に表示される項目

上部:
- 「公開用参考価格による概算です（実取引価格ではありません）」/ 税率10% / 公開フォルダ
- **再計算** ボタン / **CSV出力** ボタン / 保存先表示

テーブル（レイヤー別・mass中心）:
`layer_name, object_count, category, calc_type, volume_mm3, weight_kg, density_g_cm3,
unit_price_ex_tax, amount_ex_tax, amount_inc_tax, warning`（area_m2 は補助列）

warning の例:
- 「体積/面積が取れず見積不能」（volumeなし）
- 「kg単価未確定: mapping UI等で手入力」（単価なし）
- 「カテゴリfallback単価を使用(寸法一致なし)」（寸法完全一致なし）
- 「材質不明: 密度7.85(鉄)を仮定」（材質不明で仮計算）
- 「対象外(ignore)」（補助線）

下部（合計）:
- 税抜合計 / 消費税 / 税込合計
- recommended（中央値相当）合計 / conservative（最大値相当）合計

## 計算方針（簡素: Rhinoのvolume × kg単価）

**断面形状の正確な再現は不要**です。レイヤー内で **volume が取れたオブジェクトの体積を合計**し、
そこから重量を出して kg単価を掛けます（Rhinoの VolumeMassProperties = v1のmass計算を活用）。

- **volume があれば、形状に関係なく全カテゴリ `volume_to_weight`**（PL含む）。
  `weight_kg = total_volume_mm3 × density × 1e-6`、`amount_ex_tax = weight_kg × kg単価`、
  `amount_inc_tax = amount_ex_tax × 1.10`。
  - 例: `SQPIPE_STKR_40x40_t2.3` にただの Box が入っていても、その Box の体積を正として扱う。
  - **正確な重量にしたい場合だけ、Rhino側で正確な体積の形状にする**。概算なら簡略Boxでよい。
- volume が無く、PL/plate系で area が取れる → `area_to_weight`（fallback。`area_m2 × t × density`）。
- volume も area も無い → `object_count`（ボルト等）または `needs_review`。
- 補助線・ガイド → `ignore`。
- 密度: SS400/STK/STKR=7.85、SUS304=7.93、AL/A5052=2.70、不明=7.85+warning。
- **断面積推定・中心線長さ→定尺本数は標準ではありません**（fallback/旧仕様として残存）。

### kg単価（公開参考価格・fallbackあり）

1. レイヤー名のカテゴリ・材質・寸法が一致する kg単価
2. 一致しなければ **同カテゴリ（同材質優先）の代表 kg単価**（fallback、warningに明記）
3. それも無ければ `needs_review`（UIで手入力）

単価はレイヤー名から推定し、**必要に応じて手入力で修正**します（最終判断は人間）。
**angle/h_beam等はkg単価が公開参考に無く**、重量は出ても金額は要確認になります。

## 読み込む価格表

- `public_reference_data/public_plate_reference_prices.csv`（板材 per_kg）
- `public_reference_data/public_shape_reference_prices.csv`（形鋼 per_kg）

## CSV出力

- 出力先: Rhinoモデルと同じフォルダ、未保存なら Desktop。
- ファイル名: `steel_estimate_result.csv`、UTF-8 with BOM（Excel可）。
- 保存先はウィンドウ上に表示されます。

## 重量計算用素材 と 概算用単価カテゴリ を分けるフロー（weight_cost_estimate_rhino.py）

「素材を選ぶ」だけで金額を決めるのではなく、**2段階に分離**します。
スクリプト: `rhino_scripts/weight_cost_estimate_rhino.py`（選択オブジェクトの volume から概算材料費）。

1. **重量計算用素材（密度を決める・金属3択）** … `鉄（SS400 / STK / STKR）`=7.85、
   `ステンレス（SUS304）`=7.93、`アルミ（A5052）`=2.70（内部値 steel/stainless/aluminum）。
   **密度をざっくり決めるだけ**で、細かい規格・単価は次画面で選ぶ。木材等は Mass 専用。
2. **概算用単価カテゴリ（円/kgを決める）** … 公開参考価格CSVの細かいカテゴリから選ぶ。
   表示例:
   - `板 SS400 t6｜recommended 270円/kg｜conservative 280円/kg`
   - `板 SS400 t9｜recommended 260円/kg`
   - `角パイプ 角パイプ 40x40 t2.3｜recommended 260円/kg`
   - `丸パイプ 丸パイプ D48.6 t2.3｜recommended 290円/kg`
   - `FB FB 50x4.5｜recommended 210円/kg`
   - `pricing_mode`: recommended(中央値) / conservative(最大) / manual(手入力)

計算: `weight_kg = (raw_volume_mm3/1e9) × (density×1000)`、`cost = weight_kg × 円/kg`。
例) 1m³ Box・Steel(7.85)・PL_SS400_t6(270) → 7,850kg × 270 = **2,119,500円**。
単価カテゴリだけ PL_SS400_t9(260) に変えると重量は7,850kgのまま → **2,041,000円**。
SUS304(7.93)・manual 800 なら 7,930kg × 800 = **6,344,000円**。

- **前回値を初期表示**し、OKだけで進める。変更したい時だけ選び直す。
- 設定は `~/Documents/RhinoScripts/weight_calc_settings.json` に保存
  （`last_density_material / last_density_value / last_price_category / last_pricing_mode /
  manual_unit_prices_by_category / last_updated`）。**過去値を固定優先せず、初期表示するだけ**。
- UserText には密度用素材と価格カテゴリを**分けて**書き込む
  （`density_material / density_value / price_category / pricing_mode / unit_price_jpy_per_kg / …`）。
- angle/h_beam等はkg単価が公開参考に無いので manual を促します。

## 既存UIとの位置づけ

- **Rhino内UI（本パネル）= 標準導線**（金額を素早く見る）。
- **mapping-ui（Web）= 詳細編集・開発者向け**（単価・pricing_mode・承認フロー）。削除しません。
- **CLI = 検証・CSV処理・公開監査**（validate / estimate-public-rhino / release-audit 等）。

## 既知の限界

- RC4は表示＋CSVのみ。単価/pricing_mode編集は後続フェーズ（必要なら mapping-ui）。
- 体積が取れない開いた形状は `needs_review`（閉じたポリサーフェスにする）。
- ブロック(InstanceObject)は未展開。
- Eto.Forms UIは Rhino 実機での挙動に環境差がありうる（ロジックはpytestで検証済み）。
