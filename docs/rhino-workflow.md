# Rhino 標準ワークフロー（ポリサーフェス体積方式）

最終更新: 2026-05-31

## このツールの標準運用

- 鋼材（角パイプ・丸パイプ・アングル・FB・丸棒など）は **`ExtrudeCrv` 等で閉じた
  ポリサーフェス**として作図する。**中心線カーブでは管理しない**。
- 鋼材の見積は **体積→重量→kg単価**（`volume_to_weight`）が標準。
- 板材は面積が取れる**閉じた平面曲線 / サーフェス**で作図 → `area_to_weight`
  （厚み込みのソリッド板なら `volume_to_weight` も可）。
- 中心線カーブ方式（`curve_length_to_stock` / `curve_length_to_meter`）は
  **補助・旧仕様**として残すが、標準ではない。

## 手順

1. Rhino 8 で鋼材を**閉じたポリサーフェス**で作図（押し出し＋キャップ。中空材は内側profileで穴）。
   - レイヤー名は `<種別>_<材質>_<寸法>`（例 `SQPIPE_STKR_40x40_t2.3`）にすると自動推定が当たる。

### A. 標準導線: Rhino内UIで金額を見る（推奨）

2A. `_ScriptEditor`（Python 3 / CPython / RhinoCommon）で
   `rhino_scripts/steel_estimate_rhino_panel.py` を Run → Rhino内ウィンドウでレイヤー別金額・合計を確認
   → **CSV出力**（`steel_estimate_result.csv`）。詳細 → `docs/rhino-internal-ui-guide.md`。

### B. CLI導線（CSV経由・検証や自動化向け）

2. `export_rhino_objects.py` を ScriptEditor で Run → `rhino_objects.csv`
   （閉ソリッドなら `object_volume_mm3` が入る）。
3. CLI:
   ```bash
   python -m steel_estimator.cli validate-rhino-csv --input ./data/rhino_objects.csv
   python -m steel_estimator.cli estimate-public-rhino \
     --rhino-csv ./data/rhino_objects.csv --out-dir ./public_demo_output --tax-rate 0.10
   python -m steel_estimator.cli mapping-ui --out-dir ./public_demo_output \
     --public-reference ./public_reference_data
   ```

## 作図上の必須条件（断面再現は不要）

- **形状の正確な断面再現は不要**。各レイヤーに **volume が取れる閉じたソリッド**があればよい
  （Box でも Cylinder でも可）。見積は **そのレイヤー内の volume 合計 → 重量 → kg単価**。
- **閉じたソリッド**であること（`_Volume` で体積が出るか確認。出なければ `_Cap` / `_Join`）。
- **正確な材料重量にしたい場合だけ、Rhino側で正しい体積の形状**にする
  （中空材を実際に中空で作る等）。**概算でよければ簡略Boxでよい**。
- 体積が取れない開いた形状は、PL/plate系で面積が取れれば `area_to_weight`、
  それも無ければ **見積不能 / 要確認**（needs_review）。
- **ブロック(InstanceObject)は未展開**。内部数量・体積は集計されない（必要なら分解する）。
- 断面積推定・中心線長さ→定尺本数は標準ではない（fallback/旧仕様）。

## デモモデル（断面再現なし・volume_to_weight検証用）

`rhino_scripts/create_demo_rhino_model.py` を Run すると、**実運用に近いレイヤー名の単純Box**が
作られる（中身はBoxでよい。レイヤー内volumeを材料量として扱い、レイヤー名のkg単価を掛ける）:

`PL_SS400_t6` / `PL_SS400_t9` / `SQPIPE_STKR_40x40_t2.3` / `PIPE_STK_D48.6_t2.3` /
`FB_SS400_50x4.5` / `ANGLE_SS400_40x40_t3`（kg単価なし→warning）/ `BOLT_TEST`（object_count）/
`IGNORE_GUIDE`（ignore）。

> **断面形状の再現は不要**。レイヤー内volumeが見積根拠。正確な材料量が必要なら、ユーザーが
> Rhino上で正しい体積の形状を作る。詳細な計算式・密度・kg単価は `docs/pricing-method.md`。
